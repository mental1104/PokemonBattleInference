package httpapi

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"slices"
	"strings"
	"sync"
	"time"
)

const inferenceGraphRevision = "battle-inference.summary-exploration.v2"

// inferenceGraphError 保留原store/导航的HTTP错误类别，不包含数据库连接或worker路径。
type inferenceGraphError struct {
	status  int
	code    string
	message string
}

// Error 返回原application稳定诊断，由HTTP层统一编码转义。
func (failure *inferenceGraphError) Error() string { return failure.message }

// inferenceGraphMissing 构造原图句柄不存在诊断；id来自公开请求或服务端UUID。
func inferenceGraphMissing(id string) error {
	return &inferenceGraphError{404, "battle_graph_resource_not_found", fmt.Sprintf("battle graph '%s' was not found", id)}
}

// inferenceGraphArtifact 拥有首次真实计算的完整冻结请求、版本和计数，不保存完整图JSON。
// 发布之后全部字段只读；每次导航由独立Core使用同一事实按需重建，绝不重新查询PG。
type inferenceGraphArtifact struct {
	fixedRequest  json.RawMessage
	engineVersion string
	rulesVersion  string
	nodeCount     int
	edgeCount     int
	id            string
	revision      string
	created       time.Time
	expires       time.Time
}

// inferenceGraphStore 按原15分钟/64图/总200000节点800000边保存原图，无后台清理线程。
// mu保护entries/order/计数；图本体发布后只读，不在锁内执行Core或等待子进程。
type inferenceGraphStore struct {
	mu      sync.Mutex
	entries map[string]*inferenceGraphArtifact
	order   []string
	nodes   int
	edges   int
	now     func() time.Time
}

// newInferenceGraphStore 返回服务器实例独占的空store，构建不访问PG或启动goroutine。
func newInferenceGraphStore() *inferenceGraphStore {
	return &inferenceGraphStore{entries: map[string]*inferenceGraphArtifact{}, order: []string{}, now: time.Now}
}

// removeLocked 只由持有mu的调用方传入现存id；同步释放图与FIFO/容量计数，不保留过期墓碑。
func (store *inferenceGraphStore) removeLocked(id string) {
	artifact, exists := store.entries[id]
	if !exists {
		return
	}
	store.nodes -= artifact.nodeCount
	store.edges -= artifact.edgeCount
	delete(store.entries, id)
	if index := slices.Index(store.order, id); index >= 0 {
		store.order = slices.Delete(store.order, index, index+1)
	}
}

// put 接管尚未发布的artifact；成功后调用方不得修改其字段或底层记录，返回只读句柄。
// 单图容量先拒绝；锁内清理过期/按写入顺序淘汰，完整发布之后才返回，失败不淘汰合法图。
func (store *inferenceGraphStore) put(artifact *inferenceGraphArtifact) (*inferenceGraphArtifact, error) {
	if artifact == nil || artifact.nodeCount < 1 || artifact.edgeCount < 0 || !json.Valid(artifact.fixedRequest) || artifact.engineVersion == "" || artifact.rulesVersion == "" {
		return nil, errors.New("fixed graph artifact is required")
	}
	if artifact.nodeCount > 200000 {
		return nil, &inferenceGraphError{503, "battle_graph_store_capacity_exceeded", fmt.Sprintf("battle graph has %d nodes, exceeding max_nodes=200000", artifact.nodeCount)}
	}
	if artifact.edgeCount > 800000 {
		return nil, &inferenceGraphError{503, "battle_graph_store_capacity_exceeded", fmt.Sprintf("battle graph has %d edges, exceeding max_edges=800000", artifact.edgeCount)}
	}
	var bytes [16]byte
	if _, err := rand.Read(bytes[:]); err != nil {
		return nil, errors.New("graph identity could not be allocated")
	}
	id := hex.EncodeToString(bytes[:])
	// 取得独立字节所有权，调用方原传输缓冲区不能改变已冻结事实。
	artifact.fixedRequest = append(json.RawMessage(nil), artifact.fixedRequest...)
	store.mu.Lock()
	defer store.mu.Unlock()
	now := store.now().UTC()
	if _, collision := store.entries[id]; collision {
		return nil, errors.New("graph identity collision")
	}
	for existing, graph := range store.entries {
		if !graph.expires.After(now) {
			store.removeLocked(existing)
		}
	}
	for len(store.entries) >= 64 || store.nodes+artifact.nodeCount > 200000 || store.edges+artifact.edgeCount > 800000 {
		if len(store.order) == 0 {
			return nil, errors.New("graph store capacity accounting is inconsistent")
		}
		store.removeLocked(store.order[0])
	}
	artifact.id, artifact.created, artifact.expires = id, now, now.Add(15*time.Minute)
	store.entries[id] = artifact
	store.order = append(store.order, id)
	store.nodes += artifact.nodeCount
	store.edges += artifact.edgeCount
	return artifact, nil
}

// get 返回不可变图借用；首次过期读取删除并返回410，之后读取按原行为返回404。
// id必须是规范化公开标识；锁只保护生命周期，取得后Core计算不会持锁。
func (store *inferenceGraphStore) get(id string) (*inferenceGraphArtifact, error) {
	if id == "" || strings.TrimSpace(id) != id {
		return nil, inferenceGraphMissing(id)
	}
	store.mu.Lock()
	defer store.mu.Unlock()
	artifact, exists := store.entries[id]
	if !exists {
		return nil, inferenceGraphMissing(id)
	}
	if !artifact.expires.After(store.now().UTC()) {
		store.removeLocked(id)
		return nil, &inferenceGraphError{410, "battle_graph_expired", fmt.Sprintf("battle graph '%s' has expired", id)}
	}
	return artifact, nil
}
