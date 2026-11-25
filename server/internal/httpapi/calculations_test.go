package httpapi

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"reflect"
	"strconv"
	"syscall"
	"testing"
	"time"
)

// testWorker 优先使用显式测试产物，否则真实编译指定 target；缺失环境绝不跳过原 HTTP 断言。
// executable 在可执行 GOTMPDIR 下生成，清理仅针对本测试拥有的目录，沿用调用方 CGO 库路径。
func testWorker(t *testing.T, environment, target, name string) string {
	t.Helper()
	if value := os.Getenv(environment); value != "" {
		if !filepath.IsAbs(value) {
			t.Fatal("test worker must be an absolute path")
		}
		return value
	}
	directory, err := os.MkdirTemp(os.Getenv("GOTMPDIR"), "pbi-http-worker-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := os.RemoveAll(directory); err != nil {
			t.Error(err)
		}
	})
	executable := filepath.Join(directory, name)
	module, err := filepath.Abs("../..")
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Minute)
	defer cancel()
	command := exec.CommandContext(ctx, "go", "build", "-a", "-o", executable, target)
	command.Dir = module
	if output, err := command.CombinedOutput(); err != nil {
		t.Fatalf("build actual HTTP child: %v\n%s", err, output)
	}
	return executable
}

// TestHTTPCoreRoundTrip 通过真实回环 HTTP 与独立 CGO/Core 子进程完整比较共享响应。
func TestHTTPCoreRoundTrip(t *testing.T) {
	worker := testWorker(t, "PBI_TEST_CORE_WORKER", "./cmd/pbi-core-worker", "pbi-core-worker")
	t.Setenv("PBI_CORE_WORKER_PATH", worker)
	root := os.Getenv("PBI_CONTRACT_FIXTURES")
	if root == "" {
		root = "../../../tests/vectors"
	}
	request, err := os.ReadFile(filepath.Join(root, "abi-calculations.v1.request.json"))
	if err != nil {
		t.Fatal(err)
	}
	expected, err := os.ReadFile(filepath.Join(root, "abi-calculations.v1.response.json"))
	if err != nil {
		t.Fatal(err)
	}
	handler := Handler()
	server := httptest.NewServer(handler)
	defer server.Close()
	response, err := http.Post(server.URL+"/v1/core/calculate", "application/json", bytes.NewReader(request))
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	body, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatal(err)
	}
	var got, want any
	if err := json.Unmarshal(body, &got); err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(expected, &want); err != nil {
		t.Fatal(err)
	}
	if response.StatusCode != 200 || !reflect.DeepEqual(got, want) {
		t.Fatalf("HTTP mismatch: %d %s", response.StatusCode, body)
	}
	bad, err := http.Post(server.URL+"/v1/core/calculate", "application/json", bytes.NewBufferString("{"))
	if err != nil {
		t.Fatal(err)
	}
	defer bad.Body.Close()
	if bad.StatusCode != 400 {
		t.Fatalf("invalid input returned %d", bad.StatusCode)
	}
	unsupported, err := http.Post(server.URL+"/v1/core/calculate", "application/json", bytes.NewBufferString(`{"schema_version":1,"operations":[{"kind":"unknown"}]}`))
	if err != nil {
		t.Fatal(err)
	}
	defer unsupported.Body.Close()
	if unsupported.StatusCode != 422 {
		t.Fatalf("unsupported input returned %d", unsupported.StatusCode)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	cancelled := httptest.NewRequest("POST", "/v1/core/calculate", bytes.NewReader(request)).WithContext(ctx)
	recorder := httptest.NewRecorder()
	handler.ServeHTTP(recorder, cancelled)
	if recorder.Code != 408 {
		t.Fatalf("cancelled context returned %d %s", recorder.Code, recorder.Body)
	}
}

// TestMissingCoreWorkerNeverFallsBack 确认最简单 HP 请求也必须使用绝对且可用的配置子进程。
func TestMissingCoreWorkerNeverFallsBack(t *testing.T) {
	for _, path := range []string{filepath.Join(t.TempDir(), "missing-worker"), "relative-worker"} {
		t.Setenv("PBI_CORE_WORKER_PATH", path)
		request := httptest.NewRequest("POST", "/v1/core/calculate", bytes.NewBufferString(`{"schema_version":1,"operations":[{"kind":"hp","base":95,"iv":31,"ev":252,"level":50}]}`))
		response := httptest.NewRecorder()
		Handler().ServeHTTP(response, request)
		if response.Code != 503 || !bytes.Contains(response.Body.Bytes(), []byte("worker_unavailable")) {
			t.Fatalf("missing worker used fallback: %d %s", response.Code, response.Body)
		}
	}
}

// TestCGOCrashLeavesHTTPProcessAlive 通过真实 CGO SIGSEGV 子进程验证 500 和后续 health，不模拟计算结果。
func TestCGOCrashLeavesHTTPProcessAlive(t *testing.T) {
	worker := testWorker(t, "PBI_TEST_CRASH_WORKER", "./internal/workerprocess/testdata/crashing-worker", "pbi-crash-worker")
	t.Setenv("PBI_CORE_WORKER_PATH", worker)
	server := httptest.NewServer(Handler())
	defer server.Close()
	response, err := http.Post(server.URL+"/v1/core/calculate", "application/json", bytes.NewBufferString(`{"schema_version":1,"operations":[]}`))
	if err != nil {
		t.Fatal(err)
	}
	body, err := io.ReadAll(response.Body)
	response.Body.Close()
	if err != nil {
		t.Fatal(err)
	}
	if response.StatusCode != 500 || !bytes.Contains(body, []byte("worker_crash")) {
		t.Fatalf("CGO HTTP crash classification differs: %d %s", response.StatusCode, body)
	}
	health, err := http.Get(server.URL + "/healthz")
	if err != nil {
		t.Fatal(err)
	}
	defer health.Body.Close()
	if health.StatusCode != 200 {
		t.Fatalf("HTTP process did not survive: %d", health.StatusCode)
	}
}

// TestWorkerDeadlineReturns504AndReapsProcess 验证超时发生在实际子进程已启动之后，504 写出前完成回收。
func TestWorkerDeadlineReturns504AndReapsProcess(t *testing.T) {
	worker := testWorker(t, "PBI_TEST_SLOW_WORKER", "./internal/httpapi/testdata/slow-worker", "pbi-slow-worker")
	marker := filepath.Join(t.TempDir(), "started.pid")
	t.Setenv("PBI_HTTP_TEST_STARTED", marker)
	mux := http.NewServeMux()
	mux.Handle("POST /v1/core/calculate", coreHandler{worker: worker, timeout: 200 * time.Millisecond})
	mux.HandleFunc("GET /healthz", health)
	server := httptest.NewUnstartedServer(mux)
	server.Config.WriteTimeout = 2 * time.Second
	server.Start()
	defer server.Close()
	start := time.Now()
	response, err := http.Post(server.URL+"/v1/core/calculate", "application/json", bytes.NewBufferString(`{"schema_version":1,"operations":[]}`))
	if err != nil {
		t.Fatal(err)
	}
	body, err := io.ReadAll(response.Body)
	response.Body.Close()
	if err != nil {
		t.Fatal(err)
	}
	if response.StatusCode != 504 || time.Since(start) > time.Second {
		t.Fatalf("deadline did not return promptly: %d %s", response.StatusCode, body)
	}
	data, err := os.ReadFile(marker)
	if err != nil {
		t.Fatalf("deadline fired before child startup: %v", err)
	}
	pid, err := strconv.Atoi(string(data))
	if err != nil {
		t.Fatal(err)
	}
	process, err := os.FindProcess(pid)
	if err != nil {
		t.Fatal(err)
	}
	err = process.Signal(syscall.Signal(0))
	if !errors.Is(err, os.ErrProcessDone) && !errors.Is(err, syscall.ESRCH) {
		t.Fatalf("timed out child still exists pid=%d err=%v", pid, err)
	}
}
