package httpapi

import (
	"encoding/json"
	"errors"
	"strings"
	"sync"
	"testing"
	"time"
)

// graphStoreArtifact 只构造存储容量元数据，不伪造Core规则、图求解或HTTP推演结果。
// nodes是已计算图的计数占位；冻结请求不交给Core，测试仅验证store生命周期。
func graphStoreArtifact(nodes int) *inferenceGraphArtifact {
	return &inferenceGraphArtifact{revision: inferenceGraphRevision, fixedRequest: json.RawMessage(`{"kind":"fixed_battle"}`), engineVersion: "storage-test", rulesVersion: "storage-test", nodeCount: nodes}
}

// TestInferenceGraphStoreLifecycle 验证原15分钟边界、首次410后404以及无墓碑的容量释放。
func TestInferenceGraphStoreLifecycle(t *testing.T) {
	store := newInferenceGraphStore()
	now := time.Date(2026, 11, 24, 1, 0, 0, 0, time.UTC)
	store.now = func() time.Time { return now }
	artifact, err := store.put(graphStoreArtifact(1))
	if err != nil {
		t.Fatal(err)
	}
	if len(artifact.id) != 32 || !artifact.expires.Equal(now.Add(15*time.Minute)) {
		t.Fatalf("invalid graph handle: %#v", artifact)
	}
	now = artifact.expires.Add(-time.Nanosecond)
	if _, err = store.get(artifact.id); err != nil {
		t.Fatal(err)
	}
	now = artifact.expires
	_, err = store.get(artifact.id)
	var failure *inferenceGraphError
	if !errors.As(err, &failure) || failure.status != 410 {
		t.Fatalf("first expired read: %v", err)
	}
	_, err = store.get(artifact.id)
	if !errors.As(err, &failure) || failure.status != 404 {
		t.Fatalf("second expired read: %v", err)
	}
	if store.nodes != 0 || store.edges != 0 || len(store.order) != 0 || len(store.entries) != 0 {
		t.Fatal("expired artifact retained capacity")
	}
}

// TestInferenceGraphStoreFIFO 验证写入顺序淘汰，读取旧图不会把它提升成LRU。
func TestInferenceGraphStoreFIFO(t *testing.T) {
	store := newInferenceGraphStore()
	first, err := store.put(graphStoreArtifact(1))
	if err != nil {
		t.Fatal(err)
	}
	for index := 0; index < 63; index++ {
		if _, err = store.put(graphStoreArtifact(1)); err != nil {
			t.Fatal(err)
		}
	}
	if _, err = store.get(first.id); err != nil {
		t.Fatal(err)
	}
	if _, err = store.put(graphStoreArtifact(1)); err != nil {
		t.Fatal(err)
	}
	if _, err = store.get(first.id); err == nil {
		t.Fatal("read unexpectedly changed insertion-order eviction")
	}
	if len(store.entries) != 64 || store.nodes != 64 || len(store.order) != 64 {
		t.Fatal("graph count accounting changed")
	}
}

// TestInferenceGraphStoreRejectsOversizeAtomically 验证单图超限503不淘汰已存合法图，不把部分图当成功。
func TestInferenceGraphStoreRejectsOversizeAtomically(t *testing.T) {
	store := newInferenceGraphStore()
	first, err := store.put(graphStoreArtifact(1))
	if err != nil {
		t.Fatal(err)
	}
	_, err = store.put(graphStoreArtifact(200001))
	var failure *inferenceGraphError
	if !errors.As(err, &failure) || failure.status != 503 {
		t.Fatalf("oversized graph result: %v", err)
	}
	if _, err = store.get(first.id); err != nil {
		t.Fatal(err)
	}
	if len(store.entries) != 1 || store.nodes != 1 {
		t.Fatal("rejected graph changed existing store")
	}
}

// TestInferenceGraphStoreConcurrentPublication 验证并发完整发布/读取，race检查不应发现可变记录共享。
func TestInferenceGraphStoreConcurrentPublication(t *testing.T) {
	store := newInferenceGraphStore()
	var workers sync.WaitGroup
	for index := 0; index < 16; index++ {
		workers.Add(1)
		go func() {
			defer workers.Done()
			artifact, err := store.put(graphStoreArtifact(1))
			if err != nil {
				t.Error(err)
				return
			}
			if _, err = store.get(artifact.id); err != nil {
				t.Error(err)
			}
		}()
	}
	workers.Wait()
	if len(store.entries) != 16 || store.nodes != 16 || len(store.order) != 16 {
		t.Fatal("concurrent publication lost capacity accounting")
	}
}

// TestInferenceGraphFrozenRequestOwnership 验证公开请求缓冲区复用不能改变已冻结事实或重新计算依据。
func TestInferenceGraphFrozenRequestOwnership(t *testing.T) {
	store := newInferenceGraphStore()
	input := graphStoreArtifact(841)
	input.edgeCount = 16095
	borrowed := input.fixedRequest
	stored, err := store.put(input)
	if err != nil {
		t.Fatal(err)
	}
	borrowed[0] = '['
	loaded, err := store.get(stored.id)
	if err != nil || string(loaded.fixedRequest) != `{"kind":"fixed_battle"}` || loaded.nodeCount != 841 || loaded.edgeCount != 16095 {
		t.Fatalf("frozen request changed after caller buffer reuse: %v", err)
	}
}

// TestInferenceGraphIdentityJSONMapping 验证大于uint64的Core十进制身份无损输出为旧HTTP整数，不经过float64。
func TestInferenceGraphIdentityJSONMapping(t *testing.T) {
	identity := "100010001000100010000"
	var step inferenceGraphStep
	if err := json.Unmarshal([]byte(`{"source_node_id":"`+identity+`","edge_id":"0","target_node_id":"100010001000100010001"}`), &step); err != nil {
		t.Fatal(err)
	}
	encoded, err := json.Marshal(step)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(encoded), `"source_node_id":`+identity+`,`) || strings.Contains(string(encoded), `"source_node_id":"`) {
		t.Fatalf("identity lost integer representation: %s", encoded)
	}
}
