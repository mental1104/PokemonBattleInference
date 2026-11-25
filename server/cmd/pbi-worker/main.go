// pbi-worker 只消费已冻结的 Go 任务，在独立原生子进程执行计算；不创建或猜测缺失的战斗配置。
package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"flag"
	"log"
	"os"
	"os/signal"
	"pokemonbattleinference/server/internal/corebridge"
	"pokemonbattleinference/server/internal/jobs"
	"pokemonbattleinference/server/internal/nativeworker"
	"pokemonbattleinference/server/internal/postgres"
	"syscall"
	"time"
)

// main 只记录稳定 ASCII 状态，数据库地址和原始计算输入均不写日志。
func main() {
	if err := run(); err != nil {
		log.Print("worker stopped with an execution or database error")
		os.Exit(1)
	}
}

// run 从显式 DSN/命令行建立 worker，返回关闭或失败结果；SIGTERM 回收子进程，未确认租约留待恢复。
func run() error {
	var options nativeworker.Options
	flag.StringVar(&options.Owner, "owner", "", "unique worker owner; generated when empty")
	flag.StringVar(&options.Revision, "revision", "", "required frozen calculation revision")
	flag.StringVar(&options.Executable, "native-executable", "/usr/local/bin/pbi-core-worker", "absolute native executable")
	flag.DurationVar(&options.LeaseDuration, "lease", 120*time.Second, "job and case lease duration")
	flag.DurationVar(&options.HeartbeatInterval, "heartbeat", 20*time.Second, "lease heartbeat interval")
	flag.DurationVar(&options.PollInterval, "poll", 250*time.Millisecond, "cancellation and queue polling interval")
	flag.DurationVar(&options.DatabaseTimeout, "database-timeout", 10*time.Second, "one database pulse timeout")
	flag.Parse()
	if flag.NArg() != 0 {
		return errors.New("unexpected worker argument")
	}
	options.EngineVersion = corebridge.EngineVersion()
	if options.Owner == "" {
		var identity [16]byte
		if _, err := rand.Read(identity[:]); err != nil {
			return err
		}
		options.Owner = "go-worker-" + hex.EncodeToString(identity[:])
	}
	dsn := os.Getenv("PBI_POSTGRES_DSN")
	if dsn == "" {
		return errors.New("PBI_POSTGRES_DSN is required")
	}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
	defer stop()
	startup, cancel := context.WithTimeout(ctx, 30*time.Second)
	db, err := postgres.Open(startup, dsn)
	cancel()
	if err != nil {
		return err
	}
	defer db.Close()
	worker, err := nativeworker.New(jobs.New(db), options)
	if err != nil {
		return err
	}
	log.Print("worker started")
	err = worker.Serve(ctx)
	if errors.Is(err, context.Canceled) && ctx.Err() != nil {
		return nil
	}
	return err
}
