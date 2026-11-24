package corebridge

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"reflect"
	"sync"
	"testing"
	"time"
)

// fixture 根据 suffix 读取共享 ABI 向量；t 接收读取失败，不写文件。
func fixture(t *testing.T, suffix string) []byte {
	t.Helper()
	root := os.Getenv("PBI_CONTRACT_FIXTURES")
	if root == "" {
		root = "../../../tests/vectors"
	}
	data, err := os.ReadFile(filepath.Join(root, "abi-calculations.v1."+suffix+".json"))
	if err != nil {
		t.Fatal(err)
	}
	return data
}

// TestSharedFixture 从同一原生 Core 得到完整版本/结果，不只核对数量。
func TestSharedFixture(t *testing.T) {
	actual, err := Compute(context.Background(), fixture(t, "request"))
	if err != nil {
		t.Fatal(err)
	}
	var got, want any
	if err := json.Unmarshal(actual, &got); err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(fixture(t, "response"), &want); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("response mismatch: %s", actual)
	}
	if EngineVersion() != "0.3.0" {
		t.Fatal("unexpected engine version")
	}
}

// TestErrorsAndConcurrency 验证错误正文及并发独立所有权；t 只在主测试 goroutine 断言。
func TestErrorsAndConcurrency(t *testing.T) {
	if _, err := Compute(context.Background(), make([]byte, MaxRequestBytes+1)); err == nil {
		t.Fatal("oversize request was accepted")
	} else {
		var limit *Failure
		if !errors.As(err, &limit) || limit.Status != ResourceLimit {
			t.Fatalf("unexpected size error: %v", err)
		}
	}
	response, err := Compute(context.Background(), []byte(`{"schema_version":1,"operations":[{"kind":"future"}]}`))
	var failure *Failure
	if !errors.As(err, &failure) || failure.Status != Unsupported || !json.Valid(response) {
		t.Fatalf("invalid error: %s %v", response, err)
	}
	request := fixture(t, "request")
	var group sync.WaitGroup
	errorsSeen := make(chan error, 16)
	for i := 0; i < 16; i++ {
		group.Add(1)
		go func() {
			defer group.Done()
			for j := 0; j < 16; j++ {
				if _, err := Compute(context.Background(), request); err != nil {
					errorsSeen <- err
					return
				}
			}
		}()
	}
	group.Wait()
	close(errorsSeen)
	for err := range errorsSeen {
		t.Error(err)
	}
}

// TestCancellation 证明已取消上下文不进入 C，以及实际未完成批次收到取消后退出。
func TestCancellation(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, err := Compute(ctx, fixture(t, "request")); !errors.Is(err, context.Canceled) {
		t.Fatalf("unexpected cancellation: %v", err)
	}
	rolls := make([]int, 256)
	for i := range rolls {
		rolls[i] = 1
	}
	operation := koOperation{"ko", 3, rolls}
	operations := make([]koOperation, 4096)
	for i := range operations {
		operations[i] = operation
	}
	request, err := json.Marshal(struct {
		Version    int           `json:"schema_version"`
		Operations []koOperation `json:"operations"`
	}{1, operations})
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel = context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	go func() { _, err := Compute(ctx, request); done <- err }()
	select {
	case err := <-done:
		t.Fatalf("batch finished before cancellation: %v", err)
	case <-time.After(time.Millisecond):
	}
	cancel()
	select {
	case err := <-done:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("unexpected cancellation result: %v", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("native cancellation timed out")
	}
}

// koOperation 是测试中的固定 KO 请求，不通过 map 拼装 schema。
type koOperation struct {
	Kind  string `json:"kind"`
	HP    int    `json:"defender_hp"`
	Rolls []int  `json:"rolls"`
}
