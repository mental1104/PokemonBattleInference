// Package jobs 在原运行表中维护任务、精确结果与租约，计算规则仍由 Core 拥有。
package jobs

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"math/big"
	"strconv"
	"strings"
	"time"
)

// Status 是原数据库合同中的任务或 case 生命周期状态。
type Status string

const (
	Pending               Status = "pending"
	Preparing             Status = "preparing"
	Running               Status = "running"
	Succeeded             Status = "succeeded"
	CompletedWithFailures Status = "completed_with_failures"
	CancelRequested       Status = "cancel_requested"
	Cancelled             Status = "cancelled"
	Failed                Status = "failed"
	Truncated             Status = "truncated"
)

var (
	// ErrNotFound 表示任务或 case 不存在。
	ErrNotFound = errors.New("job or case not found")
	// ErrLeaseConflict 表示 owner、状态或有效期不允许当前操作。
	ErrLeaseConflict = errors.New("job or case lease conflict")
	// ErrRevision 表示 worker 与冻结计算语义版本不一致。
	ErrRevision = errors.New("calculation revision mismatch")
	// ErrConflict 表示同一幂等 ID 已存在不同定义或最终结果。
	ErrConflict = errors.New("job or result conflict")
	// ErrTransition 表示当前状态禁止执行请求的生命周期操作。
	ErrTransition = errors.New("invalid job transition")
)

// terminalJob 判断 status 是否为不可再次领取的任务终态。
func terminalJob(status Status) bool {
	return status == Succeeded || status == CompletedWithFailures || status == Cancelled || status == Failed
}

// terminalCase 判断 status 是否为拥有稳定最终结果的 case 终态。
func terminalCase(status Status) bool {
	return status == Succeeded || status == Failed || status == Truncated || status == Cancelled
}

// Lease 保存一次领取后必须完整存在的 owner、心跳和截止时间。
type Lease struct {
	Owner       string
	ExpiresAt   time.Time
	HeartbeatAt time.Time
}

// validateLease 拒绝空 owner、零时间和非正期限，返回本次租约截止时间。
func validateLease(owner string, now time.Time, duration time.Duration) (time.Time, error) {
	if strings.TrimSpace(owner) == "" || now.IsZero() || duration <= 0 {
		return time.Time{}, errors.New("owner, timestamp and positive lease duration are required")
	}
	return now.Add(duration), nil
}

// ExecutionSpec 冻结原任务并行、策略和图资源预算，避免重启改变问题定义。
type ExecutionSpec struct {
	ContractVersion    string `json:"contract_version"`
	WeightAssumption   string `json:"weight_assumption"`
	AttackerPolicy     string `json:"attacker_policy"`
	DefenderPolicy     string `json:"defender_policy"`
	MechanismAdmission string `json:"mechanism_admission"`
	ProcessCount       int    `json:"process_count"`
	QueueDepth         int    `json:"queue_depth"`
	MaxNodes           int    `json:"max_nodes_per_pair"`
	MaxEdges           int    `json:"max_edges_per_pair"`
	MaxTurns           *int   `json:"max_turns"`
}

// Validate 检查 spec 满足原 SQL 范围及 one-on-one 合同中的有限枚举。
func (spec ExecutionSpec) Validate() error {
	if spec.ContractVersion != "one-on-one-move-pool.v1" || spec.WeightAssumption != "uniform_configuration_pair" || spec.MechanismAdmission != "supported_only" {
		return errors.New("unsupported execution contract")
	}
	for _, policy := range []string{spec.AttackerPolicy, spec.DefenderPolicy} {
		if policy != "first-legal-action" && policy != "uniform-random" {
			return errors.New("unsupported action policy")
		}
	}
	if spec.ProcessCount < 1 || spec.ProcessCount > 8 || spec.QueueDepth < spec.ProcessCount || spec.QueueDepth > 32 || spec.MaxNodes < 1 || spec.MaxNodes > 2000000 || spec.MaxEdges < 1 || spec.MaxEdges > 8000000 {
		return errors.New("execution budget exceeds supported bounds")
	}
	if spec.MaxTurns != nil && (*spec.MaxTurns < 1 || *spec.MaxTurns > 10000) {
		return errors.New("invalid max_turns")
	}
	return nil
}

// CaseDefinition 保存原稳定配置身份和招式列表，不依赖当前运行中的内存注册表。
// CoreRequest 为空仅允许共享 CoreTemplate 或明确 PreparationFailure，避免复制属性矩阵或伪造失败配置。
type CaseDefinition struct {
	PairID        string          `json:"configuration_pair_id"`
	AttackerID    string          `json:"attacker_configuration_id"`
	DefenderID    string          `json:"defender_configuration_id"`
	AttackerMoves []int           `json:"attacker_move_ids"`
	DefenderMoves []int           `json:"defender_move_ids"`
	CoreRequest   json.RawMessage `json:"core_request,omitempty"`
}

// Definition 是已由应用层完成知识与机制准入的完整任务，不直接暴露为 HTTP 输入。
// CoreTemplate/Admission/PreparationFailure 是可选拥有值；省略时保持旧定义 JSON 与幂等哈希兼容。
type Definition struct {
	ID                 string               `json:"job_id"`
	RulesetID          string               `json:"ruleset_id"`
	VersionGroupID     int                  `json:"version_group_id"`
	Revision           string               `json:"calculation_revision"`
	Spec               ExecutionSpec        `json:"execution"`
	Cases              []CaseDefinition     `json:"cases"`
	CoreTemplate       *FixedBattleTemplate `json:"core_request_template,omitempty"`
	Admission          json.RawMessage      `json:"admission,omitempty"`
	PreparationFailure *PreparationFailure  `json:"preparation_failure,omitempty"`
}

// Validate 检查任务身份、预算和有序用例唯一性；不执行战斗合法性推断。
func (definition Definition) Validate() error {
	if strings.TrimSpace(definition.ID) == "" || strings.TrimSpace(definition.RulesetID) == "" || definition.VersionGroupID <= 0 || strings.TrimSpace(definition.Revision) == "" || len(definition.Cases) == 0 {
		return errors.New("complete job identity and nonempty cases are required")
	}
	if err := definition.Spec.Validate(); err != nil {
		return err
	}
	// 准备失败与两种可执行请求严格互斥；旧定义省略此字段时 JSON/幂等哈希完全不变。
	if definition.PreparationFailure != nil {
		if definition.CoreTemplate != nil {
			return errors.New("preparation failure and Core template cannot be mixed")
		}
		if err := definition.PreparationFailure.Validate(); err != nil {
			return err
		}
	}
	if len(definition.Admission) > 0 && (len(definition.Admission) > 8<<20 || !json.Valid(definition.Admission)) {
		return errors.New("bounded complete admission JSON is required")
	}
	seen := map[string]bool{}
	for _, item := range definition.Cases {
		if strings.TrimSpace(item.PairID) == "" || strings.TrimSpace(item.AttackerID) == "" || strings.TrimSpace(item.DefenderID) == "" || seen[item.PairID] {
			return errors.New("case identities must be nonempty and unique")
		}
		if definition.PreparationFailure != nil {
			if len(item.CoreRequest) != 0 {
				return errors.New("preparation failure and Core requests cannot be mixed")
			}
		} else if definition.CoreTemplate == nil {
			if len(item.CoreRequest) > 8<<20 || !json.Valid(item.CoreRequest) {
				return errors.New("bounded immutable Core request is required")
			}
			var batch struct {
				SchemaVersion int               `json:"schema_version"`
				Operations    []json.RawMessage `json:"operations"`
			}
			if err := json.Unmarshal(item.CoreRequest, &batch); err != nil || batch.SchemaVersion != 1 || len(batch.Operations) == 0 {
				return errors.New("Core request must be a nonempty version 1 batch")
			}
		} else if len(item.CoreRequest) != 0 {
			return errors.New("shared template and per-case Core requests cannot be mixed")
		}
		seen[item.PairID] = true
		for _, moves := range [][]int{item.AttackerMoves, item.DefenderMoves} {
			if len(moves) < 1 || len(moves) > 4 {
				return errors.New("a configuration must contain one to four moves")
			}
			previous := 0
			for _, id := range moves {
				if id <= previous {
					return errors.New("moves must be positive, unique and sorted")
				}
				previous = id
			}
		}
	}
	if definition.CoreTemplate != nil {
		return definition.CoreTemplate.Validate(definition.Cases)
	}
	return nil
}

// Counts 保留原进度桶与累计资源；Total 必须等于所有状态桶之和。
type Counts struct {
	Total, Pending, Running, Succeeded, Failed, Truncated, Cancelled int
	Nodes, Edges, Budget                                             int64
}

// Job 是独立于驱动的冻结任务快照。
type Job struct {
	ID, RulesetID, Revision                   string
	VersionGroupID                            int
	Status                                    Status
	Attempts                                  int
	Lease                                     *Lease
	Counts                                    Counts
	Spec                                      ExecutionSpec
	CreatedAt, UpdatedAt                      time.Time
	StartedAt, CompletedAt, CancelRequestedAt *time.Time
	FailureCode, Diagnostic                   *string
}

// Case 是单用例状态及拥有租约的快照。
type Case struct {
	JobID      string
	Sequence   int
	Definition CaseDefinition
	Status     Status
	Attempts   int
	Lease      *Lease
	Result     *Result
	Progress   Progress
	UpdatedAt  time.Time
}

// Fraction 使用十进制字符串保存任意精度有理数，不经浮点或 int64 截断。
type Fraction struct {
	Numerator   string `json:"numerator"`
	Denominator string `json:"denominator"`
}

// rational 解析 fraction 并验证非负分子、正分母与可选的概率上界，返回约分后的值。
func (fraction Fraction) rational(probability bool) (*big.Rat, error) {
	numerator, ok := new(big.Int).SetString(fraction.Numerator, 10)
	if !ok || numerator.Sign() < 0 {
		return nil, errors.New("fraction numerator must be a nonnegative integer")
	}
	denominator, ok := new(big.Int).SetString(fraction.Denominator, 10)
	if !ok || denominator.Sign() <= 0 {
		return nil, errors.New("fraction denominator must be positive")
	}
	if probability && numerator.Cmp(denominator) > 0 {
		return nil, errors.New("probability must not exceed one")
	}
	return new(big.Rat).SetFrac(numerator, denominator), nil
}

// ExpectedTurns 区分有限分数、无限与无法计算，不用浮点无穷混淆语义。
type ExpectedTurns struct {
	Kind  string    `json:"kind"`
	Value *Fraction `json:"value"`
}

// Result 对应旧 case 终态合同，成功与失败字段互斥。
type Result struct {
	Status                         Status
	AttackerWin, DefenderWin, Draw *Fraction
	ExpectedTurns                  *ExpectedTurns
	Nodes, Edges, Budget           int64
	Explanation                    *string
	FailureCode, Diagnostic        *string
}

// ValidFailureCode 判断 code 是否属于原结果/诊断查询合同，不接受任意数据库文本作为有效过滤枚举。
func ValidFailureCode(code string) bool {
	switch code {
	case "unsupported_mechanism", "graph_node_limit", "graph_edge_limit", "turn_limit", "solver_unresolved", "worker_crash", "calculation_revision_mismatch", "cancelled", "invalid_configuration":
		return true
	}
	return false
}

// Normalize 验证 result 并约分全部精确分数，返回可安全持久化的独立值。
func (result Result) Normalize() (Result, error) {
	if !terminalCase(result.Status) || result.Nodes < 0 || result.Edges < 0 || result.Budget < 0 {
		return result, errors.New("terminal status and nonnegative resources are required")
	}
	if result.Status == Succeeded {
		if result.FailureCode != nil || result.Diagnostic != nil || result.ExpectedTurns == nil {
			return result, errors.New("successful result requires expected turns and no failure")
		}
		sum := new(big.Rat)
		for _, field := range []**Fraction{&result.AttackerWin, &result.DefenderWin, &result.Draw} {
			if *field == nil {
				return result, errors.New("successful result requires all probabilities")
			}
			value, err := (**field).rational(true)
			if err != nil {
				return result, err
			}
			*field = &Fraction{value.Num().String(), value.Denom().String()}
			sum.Add(sum, value)
		}
		if sum.Cmp(big.NewRat(1, 1)) != 0 {
			return result, errors.New("probabilities must sum to one")
		}
		turns := *result.ExpectedTurns
		if turns.Kind == "finite" {
			if turns.Value == nil {
				return result, errors.New("finite turns require a fraction")
			}
			value, err := turns.Value.rational(false)
			if err != nil {
				return result, err
			}
			turns.Value = &Fraction{value.Num().String(), value.Denom().String()}
		} else if (turns.Kind != "infinite" && turns.Kind != "unavailable") || turns.Value != nil {
			return result, errors.New("invalid expected turns")
		}
		result.ExpectedTurns = &turns
		if result.Explanation != nil {
			if !json.Valid([]byte(*result.Explanation)) {
				return result, errors.New("explanation must be JSON")
			}
		}
	} else {
		if result.AttackerWin != nil || result.DefenderWin != nil || result.Draw != nil || result.ExpectedTurns != nil || result.Explanation != nil || result.FailureCode == nil || strings.TrimSpace(*result.FailureCode) == "" || result.Diagnostic == nil || strings.TrimSpace(*result.Diagnostic) == "" {
			return result, errors.New("non-success result requires only failure diagnostics")
		}
		if (result.Status == Cancelled) != (*result.FailureCode == "cancelled") {
			return result, errors.New("cancelled failure code is reserved for cancelled cases")
		}
		if !ValidFailureCode(*result.FailureCode) {
			return result, errors.New("unknown inference failure code")
		}
	}
	return result, nil
}

// fractionText 生成旧 Python 指纹使用的规范分数字符串，nil 表示空槽。
func fractionText(value *Fraction) string {
	if value == nil {
		return ""
	}
	return value.Numerator + "/" + value.Denominator
}

// Fingerprint 使用与旧仓库相同的分隔、字段顺序和 SHA-256，调用前必须 Normalize。
func (result Result) Fingerprint() string {
	turns := ""
	if result.ExpectedTurns != nil {
		turns = result.ExpectedTurns.Kind
		if result.ExpectedTurns.Value != nil {
			turns += ":" + fractionText(result.ExpectedTurns.Value)
		}
	}
	explanation, code, diagnostic := "", "", ""
	if result.Explanation != nil {
		explanation = *result.Explanation
	}
	if result.FailureCode != nil {
		code = *result.FailureCode
	}
	if result.Diagnostic != nil {
		diagnostic = *result.Diagnostic
	}
	text := strings.Join([]string{string(result.Status), fractionText(result.AttackerWin), fractionText(result.DefenderWin), fractionText(result.Draw), turns, strconv.FormatInt(result.Nodes, 10), strconv.FormatInt(result.Edges, 10), strconv.FormatInt(result.Budget, 10), explanation, code, diagnostic}, "\x1f")
	digest := sha256.Sum256([]byte(text))
	return hex.EncodeToString(digest[:])
}

// Progress 保存真实构图观测，不把预算使用量解释成求解完成比例。
type Progress struct {
	Phase                                                                                         string
	ObservedNodes, ObservedEdges, ExpandedNodes, Frontier, ActionPairsCompleted, ActionPairsTotal int64
}

// Validate 拒绝负计数、不可能的展开和动作对进度。
func (progress Progress) Validate() error {
	if strings.TrimSpace(progress.Phase) == "" || progress.ObservedNodes < 0 || progress.ObservedEdges < 0 || progress.ExpandedNodes < 0 || progress.Frontier < 0 || progress.ActionPairsCompleted < 0 || progress.ActionPairsTotal < 0 || progress.ExpandedNodes > progress.ObservedNodes || progress.ActionPairsCompleted > progress.ActionPairsTotal {
		return errors.New("invalid case progress")
	}
	return nil
}
