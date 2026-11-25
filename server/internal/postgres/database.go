// Package postgres 管理 Go 服务的显式连接和向后兼容的增量运行表初始化。
package postgres

import (
	"context"
	"database/sql"
	_ "embed"
	"errors"
	_ "github.com/jackc/pgx/v5/stdlib"
	"time"
)

// runtimeSchema 由已逐项核对的六张旧运行表定义组成，不包含删除语句。
//
//go:embed runtime.sql
var runtimeSchema string

// Open 连接 dsn 指定的数据库，限制连接数并在 ctx 截止前确认可达；失败关闭连接。
// 不读取隐式生产 URL，也不自动修改 schema。
func Open(ctx context.Context, dsn string) (*sql.DB, error) {
	if dsn == "" {
		return nil, errors.New("PBI_POSTGRES_DSN is required")
	}
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(12)
	db.SetMaxIdleConns(4)
	db.SetConnMaxLifetime(30 * time.Minute)
	if err = db.PingContext(ctx); err != nil {
		_ = db.Close()
		return nil, err
	}
	return db, nil
}

// Migrate 在单事务及 advisory lock 下创建缺失运行对象，保留旧记录和主键。
// db 必须由调用方显式提供；失败回滚整个初始化，不触碰 poke_raw 或物化视图。
func Migrate(ctx context.Context, db *sql.DB) error {
	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()
	if _, err = tx.ExecContext(ctx, "SELECT pg_advisory_xact_lock(1346521427)"); err != nil {
		return err
	}
	if _, err = tx.ExecContext(ctx, runtimeSchema); err != nil {
		return err
	}
	return tx.Commit()
}
