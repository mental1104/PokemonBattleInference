package httpapi

import (
	"encoding/json"
	"errors"
	"pokemonbattleinference/server/internal/jobs"
	"strings"
)

// jobDimensions 是原 v1 的八个显式维度；只有 moves 可为候选池，不接受隐式扩大枚举。
type jobDimensions struct {
	Pokemon string `json:"pokemon"`
	Form    string `json:"form"`
	Level   string `json:"level"`
	Stats   string `json:"stats"`
	Ability string `json:"ability"`
	Item    string `json:"item"`
	Moves   string `json:"moves"`
	Special string `json:"special_mechanics"`
}

// jobFixed 只保存原固定选择；最终能力由 Core 从 stat_profile_id 解出的显式 EV/IV/nature 计算。
type jobFixed struct {
	PokemonID int     `json:"pokemon_id"`
	FormID    *int    `json:"form_id"`
	Level     int     `json:"level"`
	Profile   string  `json:"stat_profile_id"`
	Ability   string  `json:"ability_identifier"`
	Item      *string `json:"item_identifier"`
}

// jobSelection 保存一侧原固定配置与全部请求 ID；Go 不枚举招式组合或生成 case canonical 身份。
type jobSelection struct {
	Fixed jobFixed `json:"fixed"`
	Moves []int    `json:"candidate_move_ids"`
}

// jobPoolCommand 与原 one-on-one-move-pool.v1 公开 DTO 一一对应，作为 Core job_move_pool 唯一规划输入。
type jobPoolCommand struct {
	Contract       string        `json:"contract_version"`
	Ruleset        string        `json:"ruleset_id"`
	Version        int           `json:"version_group_id"`
	Revision       string        `json:"calculation_revision"`
	Dimensions     jobDimensions `json:"dimensions"`
	Weight         string        `json:"weight_assumption"`
	AttackerPolicy string        `json:"attacker_policy"`
	DefenderPolicy string        `json:"defender_policy"`
	Mechanism      string        `json:"mechanism_admission"`
	Attacker       jobSelection  `json:"attacker"`
	Defender       jobSelection  `json:"defender"`
}

// jobExecutionBudget 是原可选执行预算；省略采用原默认，max_turns 显式 null 保留无限语义。
type jobExecutionBudget struct {
	ProcessCount int  `json:"process_count"`
	QueueDepth   int  `json:"queue_depth"`
	MaxNodes     int  `json:"max_nodes_per_pair"`
	MaxEdges     int  `json:"max_edges_per_pair"`
	MaxTurns     *int `json:"max_turns"`
}

// defaultJobBudget 返回原默认的独立值和100回合指针，不共享可变全局状态。
func defaultJobBudget() jobExecutionBudget {
	turns := 100
	return jobExecutionBudget{2, 4, 20000, 80000, &turns}
}

// UnmarshalJSON 对 data 采用原省略默认，拒绝 null 对象/未知字段/非法数字类型。
func (budget *jobExecutionBudget) UnmarshalJSON(data []byte) error {
	if string(data) == "null" {
		return errors.New("execution must be an object")
	}
	type plain jobExecutionBudget
	value := plain(defaultJobBudget())
	decoder := json.NewDecoder(strings.NewReader(string(data)))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&value); err != nil {
		return err
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(data, &fields); err != nil {
		return err
	}
	for key, encoded := range fields {
		if key != "max_turns" && string(encoded) == "null" {
			return errors.New("execution budgets must be integers")
		}
	}
	*budget = jobExecutionBudget(value)
	return nil
}

// jobSubmissionRequest 在原命令上附加执行预算；Core 的 command 不包含 HTTP execution 字段。
type jobSubmissionRequest struct {
	jobPoolCommand
	Execution jobExecutionBudget `json:"execution"`
}

// validate 只实施原公开 DTO/SubmitBattleInferenceJobCommand 的边界约束，不判断任何机制或组合结果。
func (request jobSubmissionRequest) validate() error {
	command := request.jobPoolCommand
	if command.Contract != "one-on-one-move-pool.v1" {
		return errors.New("unsupported one-on-one contract version")
	}
	if command.Version <= 0 {
		return errors.New("version_group_id must be a positive integer")
	}
	if command.Revision != "battle-inference.summary-exploration.v2" {
		return errors.New("calculation_revision must match the current worker calculation revision")
	}
	for _, text := range []string{command.Ruleset, command.Revision} {
		if text == "" || text != strings.TrimSpace(text) {
			return errors.New("rule identities must be normalized and non-empty")
		}
	}
	dimensions := command.Dimensions
	for _, mode := range []string{dimensions.Pokemon, dimensions.Form, dimensions.Level, dimensions.Stats, dimensions.Ability, dimensions.Item} {
		if mode != "fixed" {
			return errors.New("v1 only allows fixed non-move dimensions")
		}
	}
	if dimensions.Moves != "candidate_pool" || dimensions.Special != "disabled" {
		return errors.New("v1 requires candidate_pool moves and disabled special mechanics")
	}
	for _, side := range []jobSelection{command.Attacker, command.Defender} {
		if side.Fixed.PokemonID <= 0 || side.Fixed.Level < 1 || side.Fixed.Level > 100 || len(side.Moves) < 1 || len(side.Moves) > 10 {
			return errors.New("positive pokemon_id, level 1..100 and one to ten candidate moves are required")
		}
		for _, text := range []string{side.Fixed.Profile, side.Fixed.Ability} {
			if text == "" || text != strings.TrimSpace(text) {
				return errors.New("fixed identities must be normalized and non-empty")
			}
		}
		if side.Fixed.Item != nil && (*side.Fixed.Item == "" || *side.Fixed.Item != strings.TrimSpace(*side.Fixed.Item)) {
			return errors.New("item_identifier must be normalized when provided")
		}
		if side.Fixed.FormID != nil {
			return errors.New("explicit form_id is not supported by the v1 worker")
		}
		seen := map[int]bool{}
		for _, id := range side.Moves {
			if id <= 0 {
				return errors.New("candidate move ids must be positive integers")
			}
			if seen[id] {
				return errors.New("candidate move ids must be unique")
			}
			seen[id] = true
		}
	}
	if command.Attacker.Fixed.Level != command.Defender.Fixed.Level {
		return errors.New("both sides must use the same battle level")
	}
	return request.spec().Validate()
}

// spec 将已选择的旧策略和显式预算冻结为持久化规格，不从运行进程取新的默认值。
func (request jobSubmissionRequest) spec() jobs.ExecutionSpec {
	budget, command := request.Execution, request.jobPoolCommand
	return jobs.ExecutionSpec{ContractVersion: command.Contract, WeightAssumption: command.Weight, AttackerPolicy: command.AttackerPolicy, DefenderPolicy: command.DefenderPolicy, MechanismAdmission: command.Mechanism, ProcessCount: budget.ProcessCount, QueueDepth: budget.QueueDepth, MaxNodes: budget.MaxNodes, MaxEdges: budget.MaxEdges, MaxTurns: budget.MaxTurns}
}

// jobAdmissionCandidate 是 Core 严格准入操作的原资料事实；Go 不填写 selectable/status 或工厂 reason。
type jobAdmissionCandidate struct {
	Source           string  `json:"source"`
	Effect           *string `json:"effect_identifier"`
	Mechanism        string  `json:"mechanism_identifier"`
	RepositoryReason string  `json:"repository_reason"`
	BaseExecutable   bool    `json:"base_executable"`
	AllowNoEffect    bool    `json:"allow_no_effect"`
}

// jobMoveSpec 是 state.v1 的完整招式传输值；这些字段只来自同一 PG snapshot。
type jobMoveSpec struct {
	MoveID int    `json:"move_id"`
	Name   string `json:"name"`
	Move   struct {
		Type     int    `json:"type"`
		Category string `json:"category"`
		Power    int    `json:"power"`
	} `json:"move"`
	MaxPP    int     `json:"max_pp"`
	Priority int     `json:"priority"`
	Accuracy *int    `json:"accuracy"`
	Effect   *string `json:"effect_identifier"`
}

// jobAdmissionFact 把相同准入事实绑定到一侧、合法 move_id 和完整 MoveSpec，交 Core 再次核对关联。
type jobAdmissionFact struct {
	Side   string       `json:"side"`
	MoveID *int         `json:"move_id"`
	Move   *jobMoveSpec `json:"move"`
	jobAdmissionCandidate
}

// jobAdmissionSnapshot 与 command 绑定规则轴；所有事实和判定将一起冻结到 Definition.Admission。
type jobAdmissionSnapshot struct {
	Ruleset    string             `json:"ruleset_id"`
	Version    int                `json:"version_group_id"`
	Revision   string             `json:"calculation_revision"`
	Candidates []jobAdmissionFact `json:"candidates"`
}

// jobAdmissionDecision 完整接收每项 Core 判定，coverage 原样保留以供审查真实缺失子能力。
type jobAdmissionDecision struct {
	Source         string          `json:"source"`
	Mechanism      string          `json:"mechanism_identifier"`
	Factory        string          `json:"factory"`
	RepositoryMode string          `json:"repository_mode"`
	Coverage       json.RawMessage `json:"coverage"`
	Status         string          `json:"status"`
	Reason         string          `json:"reason"`
	Selectable     bool            `json:"selectable"`
	Missing        []string        `json:"missing_mechanism_identifiers"`
}

// jobAdmissionFailure 对应原 HTTP 422 的每项失败；不添加原 DTO 没有的侧标识或私有字段。
type jobAdmissionFailure struct {
	Source    string   `json:"source_kind"`
	Requested string   `json:"requested_identifier"`
	Status    string   `json:"status"`
	Reason    string   `json:"reason"`
	Missing   []string `json:"missing_mechanism_identifiers"`
}

// jobPlannedCase 保存 Core 生成的原具体配置身份；Go 只转存，不生成 canonical JSON 或 side SHA。
type jobPlannedCase struct {
	Ordinal       int           `json:"ordinal"`
	PairID        string        `json:"configuration_pair_id"`
	AttackerID    string        `json:"attacker_configuration_id"`
	DefenderID    string        `json:"defender_configuration_id"`
	AttackerMoves []int         `json:"attacker_move_ids"`
	DefenderMoves []int         `json:"defender_move_ids"`
	Weight        jobs.Fraction `json:"configuration_weight"`
}

// jobPoolPage 是 Core 全局池的有界页；总数不从页面长度或 Go 组合公式推算。
type jobPoolPage struct {
	Kind      string           `json:"kind"`
	CaseCount int              `json:"case_count"`
	Offset    int              `json:"offset"`
	Next      int              `json:"next_offset"`
	HasMore   bool             `json:"has_more"`
	Cases     []jobPlannedCase `json:"cases"`
}
