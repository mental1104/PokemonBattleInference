// slow-worker 只用于验证实际子进程超时/回收，不计算或伪造任何业务结果。
package main

import (
	"os"
	"strconv"
	"time"
)

// main 在测试自有目录留下真实 PID 启动标记，再等待父进程按 deadline 终止。
func main() {
	if path := os.Getenv("PBI_HTTP_TEST_STARTED"); path != "" {
		if err := os.WriteFile(path, []byte(strconv.Itoa(os.Getpid())), 0600); err != nil {
			os.Exit(1)
		}
	}
	time.Sleep(time.Minute)
}
