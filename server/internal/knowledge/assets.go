package knowledge

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"

	"github.com/jackc/pgx/v5"
)

// SpriteReport 是原 SpriteImportResult 的 JSON 合同；重跑完全相同 manifest 不产生批次或重写 BYTEA。
type SpriteReport struct {
	ManifestHash string `json:"manifest_hash"`
	Skipped      bool   `json:"skipped"`
	FilesSeen    int    `json:"files_seen"`
	Inserted     int    `json:"inserted"`
	Updated      int    `json:"updated"`
	Unchanged    int    `json:"unchanged"`
	Storage      string `json:"storage,omitempty"`
}

// spriteStorage 明确区分保留的历史BYTEA导入与NAS元数据导入；后者绝不把正文发送到PG。
type spriteStorage uint8

const (
	spriteDatabase spriteStorage = iota
	spriteFilesystem
)

// spriteEntry 只持有一个文件的路径、长度和摘要；扫描阶段不把整套图片读入内存。
type spriteEntry struct {
	Relative string
	Absolute string
	SHA256   string
	Size     int64
}

// spriteRoot 接受 PokeAPI/sprites 仓库根目录或其中 sprites 目录，返回解析符号链接后的绝对目录。
// source 必须显式提供；缺失/类型错误在连接数据库前失败，不创建空目录或把未知目录视为空来源。
func spriteRoot(source string) (string, error) {
	if source == "" {
		return "", errors.New("sprite source is required")
	}
	root, err := filepath.EvalSymlinks(source)
	if err != nil {
		return "", fmt.Errorf("sprite source unavailable: %w", err)
	}
	root, err = filepath.Abs(root)
	if err != nil {
		return "", err
	}
	candidate := filepath.Join(root, "sprites")
	if info, statErr := os.Stat(candidate); statErr == nil && info.IsDir() {
		return candidate, nil
	}
	if info, statErr := os.Stat(root); statErr == nil && info.IsDir() && filepath.Base(root) == "sprites" {
		return root, nil
	}
	return "", errors.New("sprites directory not found under explicit source")
}

// spriteFileDigest 在 ctx 未取消时流式扫描 path，返回小写 SHA-256 和实际读取字节数。
// path 必须为普通文件；每块检查取消，打开的描述符在函数返回前关闭。
func spriteFileDigest(ctx context.Context, path string) (string, int64, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", 0, err
	}
	defer file.Close()
	digest := sha256.New()
	buffer := make([]byte, 1024*1024)
	var size int64
	for {
		if err = ctx.Err(); err != nil {
			return "", 0, err
		}
		count, readErr := file.Read(buffer)
		if count > 0 {
			_, _ = digest.Write(buffer[:count])
			size += int64(count)
		}
		if errors.Is(readErr, io.EOF) {
			break
		}
		if readErr != nil {
			return "", 0, readErr
		}
	}
	return hex.EncodeToString(digest.Sum(nil)), size, nil
}

// spriteManifest 对 root 的全部普通文件计算与原 Python 相同的排序和 NUL 分隔摘要。
// ctx 控制扫描取消；目录 symlink 不递归，文件 symlink 与原 Path.is_file 一样保留。
// 返回的条目不拥有文件描述符；读取/枚举失败使整次扫描失败，不能进入失效旧资产阶段。
func spriteManifest(ctx context.Context, root string) ([]spriteEntry, string, error) {
	entries := []spriteEntry{}
	err := filepath.WalkDir(root, func(absolute string, entry fs.DirEntry, walkErr error) error {
		// 任何枚举错误或取消均阻止完整 manifest 发布，避免不完整目录让旧资源失效。
		if walkErr != nil {
			return walkErr
		}
		if err := ctx.Err(); err != nil {
			return err
		}
		if entry.IsDir() {
			return nil
		}
		info, err := os.Stat(absolute)
		if err != nil {
			return err
		}
		if !info.Mode().IsRegular() {
			return nil
		}
		relative, err := filepath.Rel(root, absolute)
		if err != nil {
			return err
		}
		digest, size, err := spriteFileDigest(ctx, absolute)
		if err != nil {
			return err
		}
		entries = append(entries, spriteEntry{Relative: filepath.ToSlash(relative), Absolute: absolute, SHA256: digest, Size: size})
		return nil
	})
	if err != nil {
		return nil, "", err
	}
	// 用完整相对路径排序；WalkDir 的按目录遍历顺序不等于原 sorted(Path.rglob) 的完整路径顺序。
	sort.Slice(entries, func(left, right int) bool { return entries[left].Relative < entries[right].Relative })
	digest := sha256.New()
	for _, entry := range entries {
		_, _ = io.WriteString(digest, entry.Relative+"\x00"+entry.SHA256+"\x00"+strconv.FormatInt(entry.Size, 10)+"\n")
	}
	return entries, hex.EncodeToString(digest.Sum(nil)), nil
}

// writeSprite 保存同一条稳定资产身份；storage为filesystem时content明确为SQL NULL。
// ctx/tx控制取消和事务，entry来自完整快照扫描，batch记录来源commit；返回原统计分类。
// 文件正文由只读的版本化HDD快照拥有，NULL表示外部正文，不是空图片或占位响应。
func writeSprite(ctx context.Context, tx pgx.Tx, entry spriteEntry, batch int64, storage spriteStorage) (string, error) {
	metadata, err := parseSpritePath(entry.Relative)
	if err != nil {
		return "", err
	}
	var prior string
	err = tx.QueryRow(ctx, `SELECT sha256 FROM poke_raw.sprite_assets WHERE relative_path=$1`, entry.Relative).Scan(&prior)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return "", err
	}
	insert := errors.Is(err, pgx.ErrNoRows)
	classification := "unchanged"
	if insert {
		classification = "inserted"
	} else if prior != entry.SHA256 {
		classification = "updated"
	}
	var content []byte
	if storage == spriteDatabase && classification != "unchanged" {
		content, err = os.ReadFile(entry.Absolute)
		if err != nil {
			return "", err
		}
		digest := sha256.Sum256(content)
		if int64(len(content)) != entry.Size || hex.EncodeToString(digest[:]) != entry.SHA256 {
			return "", errors.New("sprite source changed after manifest scan")
		}
	}
	arguments := []any{metadata.Category, metadata.PokemonID, metadata.Generation, metadata.Version, metadata.Collection, metadata.RenderStyle, metadata.Slot, metadata.Front, metadata.Back, metadata.Female, metadata.Shiny, metadata.Animated, metadata.Status, spriteMIME(entry.Relative), entry.Size, entry.SHA256, batch, entry.Relative}
	if insert {
		arguments = append(arguments, content)
		_, err = tx.Exec(ctx, `INSERT INTO poke_raw.sprite_assets(asset_category,pokemon_id,generation_identifier,version_identifier,collection,render_style,sprite_slot,is_front,is_back,is_female,is_shiny,is_animated,parse_status,mime_type,byte_size,sha256,last_seen_batch_id,relative_path,content,first_seen_batch_id,is_active) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19,$17,true)`, arguments...)
	} else {
		query := `UPDATE poke_raw.sprite_assets SET asset_category=$1,pokemon_id=$2,generation_identifier=$3,version_identifier=$4,collection=$5,render_style=$6,sprite_slot=$7,is_front=$8,is_back=$9,is_female=$10,is_shiny=$11,is_animated=$12,parse_status=$13,mime_type=$14,byte_size=$15,sha256=$16,last_seen_batch_id=$17,is_active=true`
		if classification == "updated" || storage == spriteFilesystem {
			query += `,content=$19`
			arguments = append(arguments, content)
		}
		_, err = tx.Exec(ctx, query+` WHERE relative_path=$18`, arguments...)
	}
	return classification, err
}

// InitializeSprites 显式将完整本地 sprites 源导入原 BYTEA/schema，并刷新两个依赖图片的原 MV。
// ctx 控制全部读盘/SQL取消；dsn 仅指向已初始化或获授权的库，source 是完整资源根目录，
// sourceCommit 是可选来源标记而非自动 git 操作。返回原统计合同；失败回滚所有资源和批次。
// 完整 manifest 相同时只读复用；只有全部逐文件成功后才停用上游已移除的资产。
func InitializeSprites(ctx context.Context, dsn, source, sourceCommit string) (SpriteReport, error) {
	return initializeSprites(ctx, dsn, source, sourceCommit, spriteDatabase)
}

// InitializeSpriteFiles 对固定HDD快照仅导入元数据；正文仍由原文件和batch.source_commit定位。
// ctx控制扫描/SQL取消，dsn指向授权库，source为完整sprites快照，sourceCommit必须为40位小写Git SHA。
// 只在此显式入口将content变为可空；事务失败回滚schema/元数据，版本目录由部署方保留且只读。
func InitializeSpriteFiles(ctx context.Context, dsn, source, sourceCommit string) (SpriteReport, error) {
	if len(sourceCommit) != 40 || sourceCommit != strings.ToLower(sourceCommit) {
		return SpriteReport{}, errors.New("filesystem sprites require a 40-character lowercase source commit")
	}
	if _, err := hex.DecodeString(sourceCommit); err != nil {
		return SpriteReport{}, errors.New("filesystem sprites require a hexadecimal source commit")
	}
	return initializeSprites(ctx, dsn, source, sourceCommit, spriteFilesystem)
}

// initializeSprites 共享原完整manifest/批次/失效流程；storage决定正文所有权，不改变路径元数据合同。
// 所有数据库写入属于同一事务；文件模式只引用固定commit快照，不修改、复制或删除HDD正文。
func initializeSprites(ctx context.Context, dsn, source, sourceCommit string, storage spriteStorage) (SpriteReport, error) {
	report := SpriteReport{}
	if storage == spriteFilesystem {
		report.Storage = "filesystem"
	}
	root, err := spriteRoot(source)
	if err != nil {
		return report, err
	}
	entries, digest, err := spriteManifest(ctx, root)
	if err != nil {
		return report, fmt.Errorf("sprite manifest failed: %w", err)
	}
	report.ManifestHash, report.FilesSeen = digest, len(entries)
	if strings.TrimSpace(dsn) == "" {
		return report, errors.New("PBI_POSTGRES_DSN is required")
	}
	connection, err := pgx.Connect(ctx, dsn)
	if err != nil {
		return report, errors.New("cannot connect to explicit PostgreSQL target")
	}
	defer connection.Close(context.Background())
	tx, err := connection.Begin(ctx)
	if err != nil {
		return report, err
	}
	defer tx.Rollback(context.Background())
	// 与知识初始化共用事务锁，同时串行化同库的图片批次，保持稳定身份/first_seen。
	if _, err = tx.Exec(ctx, `SELECT pg_advisory_xact_lock(1346521428)`); err != nil {
		return report, err
	}
	if storage == spriteFilesystem {
		var required bool
		if err = tx.QueryRow(ctx, `SELECT attnotnull FROM pg_attribute WHERE attrelid='poke_raw.sprite_assets'::regclass AND attname='content' AND NOT attisdropped`).Scan(&required); err != nil {
			return report, err
		}
		// 首次切换才取得DDL锁；后续重复导入不再次锁表改变schema。
		if required {
			if _, err = tx.Exec(ctx, `ALTER TABLE poke_raw.sprite_assets ALTER COLUMN content DROP NOT NULL`); err != nil {
				return report, err
			}
		}
	}
	var hasFiles, hasDatabase bool
	if err = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM poke_raw.sprite_assets WHERE content IS NULL),EXISTS(SELECT 1 FROM poke_raw.sprite_assets WHERE is_active AND content IS NOT NULL)`).Scan(&hasFiles, &hasDatabase); err != nil {
		return report, err
	}
	// 文件模式一旦启用，历史默认入口不得无提示把正文重新灌回PG。
	if storage == spriteDatabase && hasFiles {
		return report, errors.New("filesystem sprites cannot be implicitly converted to database content")
	}
	var previous, previousSource string
	err = tx.QueryRow(ctx, `SELECT manifest_hash,coalesce(source_commit,'') FROM poke_raw.sprite_import_batches WHERE status='completed' ORDER BY completed_at DESC,id DESC LIMIT 1`).Scan(&previous, &previousSource)
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return report, err
	}
	if previous == digest && (storage == spriteDatabase || (!hasDatabase && previousSource == sourceCommit)) {
		report.Skipped, report.Unchanged = true, len(entries)
		return report, tx.Commit(ctx)
	}
	var commit *string
	if sourceCommit != "" {
		commit = &sourceCommit
	}
	var batch int64
	if err = tx.QueryRow(ctx, `INSERT INTO poke_raw.sprite_import_batches(manifest_hash,source_commit,status,files_seen) VALUES($1,$2,'running',$3) RETURNING id`, digest, commit, len(entries)).Scan(&batch); err != nil {
		return report, err
	}
	for _, entry := range entries {
		classification, writeErr := writeSprite(ctx, tx, entry, batch, storage)
		if writeErr != nil {
			return report, fmt.Errorf("sprite import failed for %s: %w", entry.Relative, writeErr)
		}
		switch classification {
		case "inserted":
			report.Inserted++
		case "updated":
			report.Updated++
		case "unchanged":
			report.Unchanged++
		}
	}
	// 每个见到的资源都已登记本批ID，因此无需把全部路径拼入 SQL，也能保留删除传播语义。
	if _, err = tx.Exec(ctx, `UPDATE poke_raw.sprite_assets SET is_active=false WHERE last_seen_batch_id<>$1`, batch); err != nil {
		return report, err
	}
	if _, err = tx.Exec(ctx, `UPDATE poke_raw.sprite_import_batches SET status='completed',completed_at=now() WHERE id=$1`, batch); err != nil {
		return report, err
	}
	for _, name := range []string{"pokemon_sprite_candidates_mv", "pokemon_sprite_by_version_group_mv"} {
		if _, err = tx.Exec(ctx, `REFRESH MATERIALIZED VIEW `+pgx.Identifier{"poke_champion", name}.Sanitize()); err != nil {
			return report, err
		}
	}
	return report, tx.Commit(ctx)
}
