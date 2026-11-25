// Package knowledge 从固定 PokeAPI CSV 及拥有模型导出的 SQL 初始化真实 PostgreSQL 知识库。
package knowledge

import (
	"context"
	"crypto/sha256"
	_ "embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
)

// 嵌入资源由 export-go-knowledge.py 从 RawBase/原 view registry 编译，保留完整来源许可。
//
//go:embed manifest.json
var manifestJSON []byte

//go:embed raw-schema.sql
var rawSchema string

//go:embed views.sql
var viewSchema string

//go:embed LICENSE.pokeapi.txt
var licenseText []byte

// ColumnKind 是旧 CSV DAO 的三个实际转换分支，空字段分别为 0、false、空文本。
type ColumnKind string

const (
	Integer ColumnKind = "integer"
	Boolean ColumnKind = "boolean"
	Text    ColumnKind = "text"
)

// Column 保留 ORM 列顺序和类型，不从 CSV 数据猜测数据库模型。
type Column struct {
	Name string     `json:"name"`
	Kind ColumnKind `json:"kind"`
}

// Table 对应一份明确的 CSV 来源和固定数据库目标。
type Table struct {
	Name         string   `json:"name"`
	RelativePath string   `json:"relative_path"`
	SHA256       string   `json:"sha256"`
	ParsedSHA256 string   `json:"parsed_sha256"`
	Columns      []Column `json:"columns"`
}

// Manifest 保留源 commit、179 张 raw 表和 177 份 CSV 的类型及内容摘要。
type Manifest struct {
	SchemaVersion   int     `json:"schema_version"`
	SourceCommit    string  `json:"source_commit"`
	License         string  `json:"license"`
	RawTableCount   int     `json:"raw_table_count"`
	RawSchemaSHA256 string  `json:"raw_schema_sha256"`
	ViewsSHA256     string  `json:"views_sha256"`
	LicenseSHA256   string  `json:"license_sha256"`
	Tables          []Table `json:"tables"`
}

// digest 返回 data 的 SHA-256，不涉及路径、环境变量或外部服务。
func digest(data []byte) string { sum := sha256.Sum256(data); return hex.EncodeToString(sum[:]) }

// Contract 返回独立清单和固定数据版本，先核验嵌入 SQL/许可摘要，损坏时明确失败。
func Contract() (Manifest, string, error) {
	var manifest Manifest
	if err := json.Unmarshal(manifestJSON, &manifest); err != nil {
		return manifest, "", err
	}
	if manifest.SchemaVersion != 1 || len(manifest.SourceCommit) != 40 || manifest.RawTableCount != 179 || len(manifest.Tables) != 177 {
		return manifest, "", errors.New("unsupported knowledge manifest")
	}
	if manifest.RawSchemaSHA256 != digest([]byte(rawSchema)) || manifest.ViewsSHA256 != digest([]byte(viewSchema)) || manifest.LicenseSHA256 != digest(licenseText) {
		return manifest, "", errors.New("embedded knowledge artifact checksum mismatch")
	}
	return manifest, "pg-pokeapi-" + manifest.SourceCommit[:12] + "-" + digest(manifestJSON)[:12], nil
}

// validateFiles 在任何数据库操作前核验 root 的全部固定来源 CSV；错误仅包含公开文件名。
func validateFiles(ctx context.Context, root string, manifest Manifest) error {
	for _, table := range manifest.Tables {
		if err := ctx.Err(); err != nil {
			return err
		}
		relative := filepath.Clean(filepath.FromSlash(table.RelativePath))
		if filepath.IsAbs(relative) || relative == ".." || len(relative) >= 3 && relative[:3] == "../" {
			return errors.New("invalid embedded CSV path")
		}
		file, err := os.Open(filepath.Join(root, relative))
		if err != nil {
			return fmt.Errorf("CSV source unavailable: %s", table.RelativePath)
		}
		hash := sha256.New()
		_, copyErr := io.Copy(hash, file)
		closeErr := file.Close()
		if copyErr != nil || closeErr != nil {
			return fmt.Errorf("cannot read CSV source: %s", table.RelativePath)
		}
		if hex.EncodeToString(hash.Sum(nil)) != table.SHA256 {
			return fmt.Errorf("CSV source checksum mismatch: %s", table.RelativePath)
		}
	}
	return nil
}
