package workerprocess

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"pokemonbattleinference/server/internal/corebridge"
	"reflect"
	"testing"
	"time"
)

const sampleProgress = `{"kind":"progress","progress":{"operation_index":0,"phase":"building","nodes":1,"edges":0,"expanded":0,"frontier":1}}`
const sampleResponse = `{"schema_version":1,"engine_version":"protocol-fixture","rules_version":"protocol-fixture","results":[]}`
const sampleResult = `{"kind":"result","response":` + sampleResponse + `}`

// TestProgressFrameReader 核对传输帧的完整字段、唯一末尾结果、保留原始字节和有限流预算。
func TestProgressFrameReader(t *testing.T) {
	reader := frameReader{}
	frame, err := reader.accept([]byte(sampleProgress))
	if err != nil || frame == nil || frame.Phase != corebridge.ProgressBuilding || frame.Nodes != 1 || frame.Frontier != 1 {
		t.Fatalf("valid progress was rejected: %v", err)
	}
	if _, err = reader.accept([]byte(sampleResult)); err != nil || string(reader.result) != sampleResponse || !reader.finished {
		t.Fatalf("result bytes were changed: %v", err)
	}
	if _, err = reader.accept([]byte(sampleProgress)); !errors.Is(err, ErrProgressProtocol) {
		t.Fatalf("frame after result was accepted: %v", err)
	}
	for _, invalid := range []string{
		`{"kind":"progress"}`,
		`{"kind":"progress","progress":{"phase":"other"}}`,
		`{"kind":"progress","progress":{"phase":"built","nodes":1,"expanded":2}}`,
		`{"kind":"progress","progress":{"phase":"built","operation_index":4096}}`,
		`{"kind":"result","response":null}`,
		`{"kind":"result","response":[]}`,
		`{"kind":"result","response":{},"unexpected":1}`,
		`{"kind":"other"}`,
		sampleResult + sampleResult,
	} {
		candidate := frameReader{}
		if _, err = candidate.accept([]byte(invalid)); !errors.Is(err, ErrProgressProtocol) {
			t.Fatalf("invalid frame accepted: %s err=%v", invalid, err)
		}
	}
	for _, candidate := range []frameReader{{frames: maxProgressFrames}, {bytes: maxProgressBytes}} {
		if _, err = candidate.accept([]byte(sampleProgress)); !errors.Is(err, ErrOutputLimit) {
			t.Fatalf("stream budget was ignored: %v", err)
		}
	}
	large := frameReader{}
	if _, err = large.accept([]byte(`{"kind":"progress","progress":{"phase":"built","nodes":2000000,"edges":8000000,"expanded":2000000}}`)); err != nil {
		t.Fatalf("legacy generated graph counts were rejected by explicit-input limits: %v", err)
	}
}

// progressExecutable 在测试独占且可执行目录创建固定传输夹具；body 是测试常量，不执行用户输入。
// 返回绝对可执行路径，目录由 t.Cleanup 清理；夹具只测流协议，不冒充 Core 业务计算。
func progressExecutable(t *testing.T, body string) string {
	t.Helper()
	if os.PathSeparator != '/' {
		t.Skip("POSIX process fixture requires a POSIX platform")
	}
	root := os.Getenv("GOTMPDIR")
	if root == "" {
		root = t.TempDir()
	}
	directory, err := os.MkdirTemp(root, "pbi-progress-protocol-")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.RemoveAll(directory) })
	executable := filepath.Join(directory, "protocol-worker")
	if err = os.WriteFile(executable, []byte("#!/bin/sh\n"+body), 0700); err != nil {
		t.Fatal(err)
	}
	return executable
}

// TestProgressProcessProtocol 使用独立进程检查末帧、重复结果和缺失结果；不把协议夹具计入数值验收。
func TestProgressProcessProtocol(t *testing.T) {
	for _, item := range []struct {
		name, body string
		valid      bool
	}{
		{"complete", "printf '%s\\n' '" + sampleProgress + "' '" + sampleResult + "'\n", true},
		{"missing-result", "printf '%s\\n' '" + sampleProgress + "'\n", false},
		{"duplicate-result", "printf '%s\\n' '" + sampleResult + "' '" + sampleResult + "'\n", false},
		{"progress-after-result", "printf '%s\\n' '" + sampleResult + "' '" + sampleProgress + "'\n", false},
	} {
		t.Run(item.name, func(t *testing.T) {
			ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			frames := 0
			response, err := ExecuteWithProgress(ctx, progressExecutable(t, item.body), []byte(`{}`), func(corebridge.Progress) { frames++ })
			if item.valid {
				if err != nil || string(response) != sampleResponse || frames != 1 {
					t.Fatalf("valid stream failed: frames=%d err=%v", frames, err)
				}
			} else if !errors.Is(err, ErrProgressProtocol) {
				t.Fatalf("invalid stream was accepted: %v", err)
			}
		})
	}
}

// TestProgressCancellationReapsChild 在收到实际子进程首帧后取消；exec sleep 替换夹具自身，避免孤儿进程。
func TestProgressCancellationReapsChild(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	executable := progressExecutable(t, "printf '%s\\n' '"+sampleProgress+"'\nexec sleep 30\n")
	frames := 0
	_, err := ExecuteWithProgress(ctx, executable, []byte(`{}`), func(corebridge.Progress) { frames++; cancel() })
	if !errors.Is(err, context.Canceled) || frames != 1 {
		t.Fatalf("cancel did not follow observed child progress: frames=%d err=%v", frames, err)
	}
}

// TestProgressCGOSegmentationIsolation 核对新流协议仍把真实 CGO SIGSEGV/exit2 归类为 worker_crash。
func TestProgressCGOSegmentationIsolation(t *testing.T) {
	executable := os.Getenv("PBI_TEST_CRASH_WORKER")
	if executable == "" {
		t.Skip("PBI_TEST_CRASH_WORKER is required for actual CGO signal integration")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_, err := ExecuteWithProgress(ctx, executable, []byte(`{}`), nil)
	var failure *Failure
	if !errors.As(err, &failure) || failure.Code != "worker_crash" {
		t.Fatalf("CGO crash was misclassified: %v", err)
	}
}

// TestActualNativeProgressProcess 使用真实独立 Core Worker 跑全部冻结向量，核对实际构图帧和完整终态。
func TestActualNativeProgressProcess(t *testing.T) {
	executable, fixtures := os.Getenv("PBI_TEST_CORE_WORKER"), os.Getenv("PBI_CONTRACT_FIXTURES")
	if executable == "" || fixtures == "" {
		t.Skip("PBI_TEST_CORE_WORKER and PBI_CONTRACT_FIXTURES are required for actual native process progress")
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
	var frames []corebridge.Progress
	response, err := ExecuteWithProgress(ctx, executable, request, func(progress corebridge.Progress) { frames = append(frames, progress) })
	if err != nil {
		t.Fatal(err)
	}
	var actual, want any
	if err = json.Unmarshal(response, &actual); err != nil {
		t.Fatal(err)
	}
	if err = json.Unmarshal(expected, &want); err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(actual, want) || len(frames) < 2 || frames[len(frames)-1].Phase != corebridge.ProgressBuilt {
		t.Fatalf("actual child did not deliver complete result and build progress: frames=%d", len(frames))
	}
	rejected, err := ExecuteWithProgress(ctx, executable, []byte(`{"schema_version":1,"operations":[{"kind":"unsupported-operation"}]}`), nil)
	var failure *Failure
	if !errors.As(err, &failure) || failure.Code != "unsupported" || len(rejected) == 0 {
		t.Fatalf("progress protocol changed explicit rejection: %v", err)
	}
}
