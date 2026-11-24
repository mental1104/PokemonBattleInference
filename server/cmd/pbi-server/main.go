// pbi-server 启动首批 Go+C++ 计算服务；默认仅监听回环，不连接生产数据库。
package main

import (
	"context"
	"errors"
	"log"
	"net/http"
	"os"
	"os/signal"
	"pokemonbattleinference/server/internal/httpapi"
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
	server := &http.Server{Addr: address, Handler: httpapi.Handler(), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 30 * time.Second, WriteTimeout: 30 * time.Second}
	go func() {
		<-ctx.Done()
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
}
