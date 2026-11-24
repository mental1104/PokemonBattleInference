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
	if EngineVersion() != "0.7.0" {
		t.Fatal("unexpected engine version")
	}
}

// TestProgressCallPreservesBatchContract 验证新增观察接口仍返回完整共享结果，非构图操作不制造进度。
func TestProgressCallPreservesBatchContract(t *testing.T) {
	observed := 0
	request := []byte(`{"schema_version":1,"operations":[{"kind":"hp","base":70,"iv":31,"ev":252,"level":50}]}`)
	actual, err := ComputeWithProgress(context.Background(), request, func(progress Progress) { observed++ })
	if err != nil {
		t.Fatal(err)
	}
	want, err := Compute(context.Background(), request)
	if err != nil {
		t.Fatal(err)
	}
	if string(actual) != string(want) || observed != 0 {
		t.Fatalf("progress path changed the batch contract: observed=%d", observed)
	}
}

// TestActualFixedBattleProgress 核对真实固定战斗的计数来自 Core 构图，且末帧与完整结果统计一致。
func TestActualFixedBattleProgress(t *testing.T) {
	var frames []Progress
	response, err := ComputeWithProgress(context.Background(), fixture(t, "request"), func(progress Progress) { frames = append(frames, progress) })
	if err != nil {
		t.Fatal(err)
	}
	if len(frames) < 2 || frames[0].Phase != ProgressBuilding || frames[len(frames)-1].Phase != ProgressBuilt {
		t.Fatalf("missing actual build lifecycle: %+v", frames)
	}
	var envelope struct {
		Results []struct {
			Kind       string `json:"kind"`
			Statistics struct {
				Nodes uint64 `json:"nodes"`
				Edges uint64 `json:"edges"`
			} `json:"statistics"`
		} `json:"results"`
	}
	if err = json.Unmarshal(response, &envelope); err != nil {
		t.Fatal(err)
	}
	last := frames[len(frames)-1]
	if int(last.OperationIndex) >= len(envelope.Results) {
		t.Fatal("invalid progress operation index")
	}
	result := envelope.Results[last.OperationIndex]
	if result.Kind != "fixed_battle" || last.Nodes != result.Statistics.Nodes || last.Edges != result.Statistics.Edges || last.Frontier != 0 {
		t.Fatalf("progress disagrees with actual result: %+v", last)
	}
	for index := 1; index < len(frames); index++ {
		if frames[index].OperationIndex == frames[index-1].OperationIndex &&
			(frames[index].Nodes < frames[index-1].Nodes || frames[index].Edges < frames[index-1].Edges || frames[index].Expanded < frames[index-1].Expanded) {
			t.Fatal("progress counts regressed")
		}
	}
}

// TestProgressCallbackPanicIsIsolated 验证观察者失败不会越过 C 栈，取消令牌/句柄清理后后续调用仍可使用。
func TestProgressCallbackPanicIsIsolated(t *testing.T) {
	response, err := ComputeWithProgress(context.Background(), fixture(t, "request"), func(Progress) { panic("test progress failure") })
	if !errors.Is(err, ErrProgressCallback) || len(response) != 0 {
		t.Fatalf("callback failure escaped or returned partial output: %v", err)
	}
	if _, err = Compute(context.Background(), fixture(t, "request")); err != nil {
		t.Fatalf("callback failure corrupted later calls: %v", err)
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
