// pbi-healthcheck 在无 shell/curl 的运行镜像中通过真实 HTTP 检查本进程网络的 API 健康。
package main

import (
	"context"
	"net"
	"net/http"
	"os"
	"time"
)

// main 仅按 HTTP 健康返回码退出，不输出环境变量、数据库地址或响应正文。
func main() {
	address := os.Getenv("PBI_LISTEN")
	if address == "" {
		address = "127.0.0.1:41105"
	}
	host, port, err := net.SplitHostPort(address)
	if err != nil {
		os.Exit(1)
	}
	if host == "0.0.0.0" || host == "" {
		host = "127.0.0.1"
	}
	if host == "::" {
		host = "::1"
	}
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, "http://"+net.JoinHostPort(host, port)+"/healthz", nil)
	if err != nil {
		os.Exit(1)
	}
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		os.Exit(1)
	}
	response.Body.Close()
	if response.StatusCode != http.StatusOK {
		os.Exit(1)
	}
}
