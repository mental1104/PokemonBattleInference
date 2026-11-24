package knowledge

import (
	"context"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/jackc/pgx/v5"
	"path/filepath"
	"strings"
)

// ErrNonempty 拒绝给未知非空知识库登记新版本；不自动清空、覆盖或认领历史数据。
var ErrNonempty = errors.New("knowledge target contains unversioned data; explicit migration is required")

// ErrVersion 表示已导入库的固定来源与本程序不同，禁止混合静态版本。
var ErrVersion = errors.New("knowledge target uses a different version")

// TableReport 保存原始 CSV 行数和按旧主键冲突规则实际插入的行数。
type TableReport struct {
	Name         string `json:"name"`
	SourceRows   int64  `json:"source_rows"`
	InsertedRows int64  `json:"inserted_rows"`
}

// Report 是可独立归档的初始化结果，版本来源、总数和复用状态均显式保留。
type Report struct {
	ImportVersion     string        `json:"import_version"`
	SourceCommit      string        `json:"source_commit"`
	RawTables         int           `json:"raw_tables"`
	CSVTables         int           `json:"csv_tables"`
	MaterializedViews int           `json:"materialized_views"`
	SourceRows        int64         `json:"source_rows"`
	InsertedRows      int64         `json:"inserted_rows"`
	Reused            bool          `json:"reused"`
	Tables            []TableReport `json:"tables"`
}

// columnsSQL 只引用嵌入模型的列名，用驱动转义而不是拼接外部 CSV header。
func columnsSQL(table Table) string {
	quoted := make([]string, len(table.Columns))
	for index, column := range table.Columns {
		quoted[index] = pgx.Identifier{column.Name}.Sanitize()
	}
	return strings.Join(quoted, ",")
}

// importTable 使用二进制 COPY 流入无约束临时表，再按旧 DAO 的主键规则去重插入。
// tx 和 root 由调用方拥有；每表结束即释放临时表与文件，不加载整个 CSV 到内存。
func importTable(ctx context.Context, tx pgx.Tx, root string, table Table) (TableReport, error) {
	report := TableReport{Name: table.Name}
	target := pgx.Identifier{"poke_raw", table.Name}.Sanitize()
	stage := pgx.Identifier{"pg_temp", "pbi_knowledge_stage"}
	if _, err := tx.Exec(ctx, `CREATE TEMP TABLE pbi_knowledge_stage(LIKE `+target+` INCLUDING DEFAULTS) ON COMMIT DROP`); err != nil {
		return report, err
	}
	source, err := openRows(filepath.Join(root, filepath.FromSlash(table.RelativePath)), table)
	if err != nil {
		return report, err
	}
	defer source.Close()
	columns := make([]string, len(table.Columns))
	for index, column := range table.Columns {
		columns[index] = column.Name
	}
	if _, err = tx.CopyFrom(ctx, stage, columns, source); err != nil {
		return report, fmt.Errorf("copy %s: %w", table.Name, err)
	}
	report.SourceRows = source.rows
	if hex.EncodeToString(source.semanticHash.Sum(nil)) != table.ParsedSHA256 {
		return report, fmt.Errorf("parsed CSV differs from legacy contract: %s", table.RelativePath)
	}
	selected := columnsSQL(table)
	command, err := tx.Exec(ctx, `INSERT INTO `+target+`(`+selected+`) SELECT `+selected+` FROM `+stage.Sanitize()+` ON CONFLICT DO NOTHING`)
	if err != nil {
		return report, fmt.Errorf("insert %s: %w", table.Name, err)
	}
	report.InsertedRows = command.RowsAffected()
	if _, err = tx.Exec(ctx, `DROP TABLE `+stage.Sanitize()); err != nil {
		return report, err
	}
	return report, nil
}

// verifyCounts 检查已登记版本的行数仍匹配首次导入，禁止缺行时静默返回复用成功。
func verifyCounts(ctx context.Context, tx pgx.Tx, report Report) error {
	for _, table := range report.Tables {
		var count int64
		if err := tx.QueryRow(ctx, `SELECT count(*) FROM `+pgx.Identifier{"poke_raw", table.Name}.Sanitize()).Scan(&count); err != nil {
			return err
		}
		if count != table.InsertedRows {
			return fmt.Errorf("knowledge row count mismatch: %s", table.Name)
		}
	}
	return nil
}

// refreshViews 按原依赖顺序刷新八个视图，不使用 DROP/重建或改变已有用户运行表。
func refreshViews(ctx context.Context, tx pgx.Tx) error {
	for _, name := range []string{"ruleset_context_mv", "pokemon_profile_mv", "move_profile_mv", "type_efficacy_mv", "pokemon_learnset_mv", "pokemon_catalog_zh_mv", "pokemon_sprite_candidates_mv", "pokemon_sprite_by_version_group_mv"} {
		if _, err := tx.Exec(ctx, `REFRESH MATERIALIZED VIEW `+pgx.Identifier{"poke_champion", name}.Sanitize()); err != nil {
			return err
		}
	}
	return nil
}

// Initialize 在自有或显式授权的空知识库里事务导入固定 CSV，并建立原八个物化视图。
// dsn 必须显式提供；先核验全部文件再连接，任何失败回滚整个数据/schema/版本写入。
// 同版本重跑验证行数后复用；refresh 才刷新已有视图，不清空任何表，也不替换未知非空库。
func Initialize(ctx context.Context, dsn, root string, refresh bool) (Report, error) {
	manifest, version, err := Contract()
	report := Report{ImportVersion: version, SourceCommit: manifest.SourceCommit, RawTables: manifest.RawTableCount, CSVTables: len(manifest.Tables), MaterializedViews: 8, Tables: []TableReport{}}
	if err != nil {
		return report, err
	}
	if err = validateFiles(ctx, root, manifest); err != nil {
		return report, err
	}
	if dsn == "" {
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
	if _, err = tx.Exec(ctx, `SELECT pg_advisory_xact_lock(1346521428)`); err != nil {
		return report, err
	}
	if _, err = tx.Exec(ctx, rawSchema); err != nil {
		return report, err
	}
	if _, err = tx.Exec(ctx, `CREATE TABLE IF NOT EXISTS poke_raw._go_knowledge_version(singleton integer PRIMARY KEY CHECK(singleton=1),import_version text NOT NULL,report json NOT NULL,imported_at timestamptz NOT NULL DEFAULT now())`); err != nil {
		return report, err
	}
	var priorVersion string
	var prior []byte
	err = tx.QueryRow(ctx, `SELECT import_version,report FROM poke_raw._go_knowledge_version WHERE singleton=1`).Scan(&priorVersion, &prior)
	if err == nil {
		if priorVersion != version {
			return report, ErrVersion
		}
		if err = json.Unmarshal(prior, &report); err != nil {
			return report, err
		}
		if err = verifyCounts(ctx, tx, report); err != nil {
			return report, err
		}
		report.Reused = true
	} else if !errors.Is(err, pgx.ErrNoRows) {
		return report, err
	} else {
		for _, table := range manifest.Tables {
			var populated bool
			if err = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM `+pgx.Identifier{"poke_raw", table.Name}.Sanitize()+` LIMIT 1)`).Scan(&populated); err != nil {
				return report, err
			}
			if populated {
				return report, ErrNonempty
			}
		}
		for _, table := range manifest.Tables {
			item, copyErr := importTable(ctx, tx, root, table)
			if copyErr != nil {
				return report, copyErr
			}
			report.Tables = append(report.Tables, item)
			report.SourceRows += item.SourceRows
			report.InsertedRows += item.InsertedRows
		}
	}
	if _, err = tx.Exec(ctx, viewSchema); err != nil {
		return report, err
	}
	if refresh {
		if err = refreshViews(ctx, tx); err != nil {
			return report, err
		}
	}
	if !report.Reused {
		data, marshalErr := json.Marshal(report)
		if marshalErr != nil {
			return report, marshalErr
		}
		if _, err = tx.Exec(ctx, `INSERT INTO poke_raw._go_knowledge_version(singleton,import_version,report) VALUES(1,$1,$2)`, version, string(data)); err != nil {
			return report, err
		}
	}
	return report, tx.Commit(ctx)
}
