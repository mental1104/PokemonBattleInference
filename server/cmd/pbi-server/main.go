// pbi-server 启动首批 Go+C++ 计算服务；默认仅监听回环，不连接生产数据库。
package main

import (
	"context"
	"database/sql"
	"errors"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"pokemonbattleinference/server/internal/httpapi"
	"pokemonbattleinference/server/internal/jobs"
	"pokemonbattleinference/server/internal/postgres"
	"pokemonbattleinference/server/internal/syncstore"
	"syscall"
	"time"
)

// main 读取 PBI_LISTEN（默认 127.0.0.1:41105），收到退出信号后最多等待十秒清理请求。
func main() {
	address := os.Getenv("PBI_LISTEN")
	if address == "" {
		address = "127.0.0.1:41105"
	}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	var db *sql.DB
	if dsn := os.Getenv("PBI_POSTGRES_DSN"); dsn != "" {
		startup, cancel := context.WithTimeout(ctx, 30*time.Second)
		var err error
		db, err = postgres.Open(startup, dsn)
		if err == nil && os.Getenv("PBI_MIGRATE") == "1" {
			err = postgres.Migrate(startup, db)
			if err == nil {
				err = jobs.New(db).Migrate(startup)
			}
			if err == nil {
				err = syncstore.New(db).Migrate(startup)
			}
		}
		cancel()
		if err != nil {
			log.Fatal("database initialization failed")
		}
		defer db.Close()
	}
	handler, err := httpapi.NewServerWithSpriteRoot(db, os.Getenv("PBI_SPRITES_ROOT"))
	if err != nil {
		log.Fatal("sprite filesystem configuration failed")
	}
	// 计算 handler 最长 30 秒；额外五秒用于可靠写出 504，socket 超时不能替代子进程取消。
	server := &http.Server{Addr: address, Handler: handler, ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 30 * time.Second, WriteTimeout: 35 * time.Second,
		BaseContext: func(_ net.Listener) context.Context { return ctx },
	}
	shutdownDone := make(chan struct{})
	go func() {
		defer close(shutdownDone)
		<-ctx.Done()
		// BaseContext 先取消正在计算的子进程，再等待 HTTP 响应退出；main 必须等到回收完成。
		shutdown, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		if err := server.Shutdown(shutdown); err != nil {
			log.Printf("shutdown failed: %v", err)
		}
	}()
	log.Printf("listening on %s", address)
	if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatal(err)
	}
	<-shutdownDone
}
