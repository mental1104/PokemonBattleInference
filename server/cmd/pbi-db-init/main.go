// pbi-db-init 显式导入固定知识 CSV、可选 sprites BYTEA 并建立运行表，HTTP 进程不承担静态知识迁移。
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"pokemonbattleinference/server/internal/jobs"
	"pokemonbattleinference/server/internal/knowledge"
	"pokemonbattleinference/server/internal/postgres"
	"pokemonbattleinference/server/internal/syncstore"
	"syscall"
	"time"
)

// main 读取明确的 CSV 根目录及环境 DSN，成功输出完整 JSON 回执，失败返回非零退出码。
func main() { os.Exit(run()) }

// run 不打印 DSN；知识初始化和运行表初始化均为可重复的显式操作，无后台常驻任务。
func run() int {
	root := flag.String("csv-root", "", "fixed PokeAPI CSV root directory")
	refresh := flag.Bool("refresh-views", false, "refresh existing compatible materialized views")
	sprites := flag.String("sprites-root", "", "optional complete PokeAPI sprites repository or sprites directory")
	spritesCommit := flag.String("sprites-commit", "", "optional explicit sprites source commit marker")
	flag.Parse()
	if *root == "" {
		fmt.Fprintln(os.Stderr, "--csv-root is required")
		return 2
	}
	signals, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	ctx, cancel := context.WithTimeout(signals, 20*time.Minute)
	defer cancel()
	dsn := os.Getenv("PBI_POSTGRES_DSN")
	report, err := knowledge.Initialize(ctx, dsn, *root, *refresh)
	if err != nil {
		fmt.Fprintf(os.Stderr, "knowledge initialization failed: %v\n", err)
		return 1
	}
	// 图片源只有显式传入才扫描；复用原完整来源失效规则，不用不完整下载静默覆盖历史图片库。
	if *sprites != "" {
		spriteReport, spriteErr := knowledge.InitializeSprites(ctx, dsn, *sprites, *spritesCommit)
		if spriteErr != nil {
			fmt.Fprintf(os.Stderr, "sprite initialization failed: %v\n", spriteErr)
			return 1
		}
		report.Sprites = &spriteReport
	}
	db, err := postgres.Open(ctx, dsn)
	if err != nil {
		fmt.Fprintln(os.Stderr, "runtime connection failed")
		return 1
	}
	defer db.Close()
	if err = postgres.Migrate(ctx, db); err == nil {
		err = jobs.New(db).Migrate(ctx)
	}
	if err == nil {
		err = syncstore.New(db).Migrate(ctx)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "runtime schema initialization failed")
		return 1
	}
	if err = json.NewEncoder(os.Stdout).Encode(report); err != nil {
		return 1
	}
	return 0
}
