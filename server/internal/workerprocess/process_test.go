package workerprocess_test

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"pokemonbattleinference/server/internal/workerprocess"
	"reflect"
	"testing"
	"time"
)

// TestNativeWorkerBoundary 在真实独立可执行文件中执行冻结向量，再验证拒绝不会破坏下一次执行。
func TestNativeWorkerBoundary(t *testing.T) {
	executable := os.Getenv("PBI_TEST_CORE_WORKER")
	fixtures := os.Getenv("PBI_CONTRACT_FIXTURES")
	if executable == "" || fixtures == "" {
		t.Skip("PBI_TEST_CORE_WORKER and PBI_CONTRACT_FIXTURES are required for native process integration")
	}
	request, err := os.ReadFile(filepath.Join(fixtures, "abi-calculations.v1.request.json"))
	if err != nil {
		t.Fatal(err)
	}
	expected, err := os.ReadFile(filepath.Join(fixtures, "abi-calculations.v1.response.json"))
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	rejected, err := workerprocess.Execute(ctx, executable, []byte(`{"schema_version":1,"operations":[{"kind":"unknown"}]}`))
	var failure *workerprocess.Failure
	if !errors.As(err, &failure) || failure.Code != "unsupported" || len(rejected) == 0 {
		t.Fatalf("unsupported classification response=%s err=%v", rejected, err)
	}
	expired, stop := context.WithCancel(context.Background())
	stop()
	if _, err = workerprocess.Execute(expired, executable, request); !errors.Is(err, context.Canceled) {
		t.Fatalf("cancel classification: %v", err)
	}
	result, err := workerprocess.Execute(ctx, executable, request)
	if err != nil {
		t.Fatal(err)
	}
	var want, got any
	if err = json.Unmarshal(expected, &want); err != nil {
		t.Fatal(err)
	}
	if err = json.Unmarshal(result, &got); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(want, got) {
		t.Fatalf("native child response differs: %s", result)
	}
}

// TestWorkerCrashIsolation 使用自有可执行脚本触发真正 SIGKILL，验证父进程识别原生崩溃类别。
// 临时脚本只有固定 shell/kill 命令，无网络、外部进程或用户输入。
func TestWorkerCrashIsolation(t *testing.T) {
	if os.PathSeparator != '/' {
		t.Skip("signal test requires a POSIX process")
	}
	root := os.Getenv("GOTMPDIR")
	if root == "" {
		root = t.TempDir()
	}
	dir, err := os.MkdirTemp(root, "pbi-worker-crash-")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(dir)
	executable := filepath.Join(dir, "worker-crash")
	if err = os.WriteFile(executable, []byte("#!/bin/sh\n# Only terminate this isolated worker process.\nkill -KILL $$\n"), 0700); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_, err = workerprocess.Execute(ctx, executable, []byte(`{}`))
	var failure *workerprocess.Failure
	if !errors.As(err, &failure) || failure.Code != "worker_crash" || failure.ExitCode != -1 {
		t.Fatalf("signal isolation failed: %v", err)
	}
}
