package httpapi

import (
	"encoding/json"
	"errors"
	"strings"
)

// inferenceChosenSide 保存原固定推演的一侧选择，不扩大到job候选池或静态calculator模板。
type inferenceChosenSide struct {
	jobFixed
	Moves []int `json:"move_ids"`
}

// UnmarshalJSON 仅为省略level应用原50级默认；显式null和错误整数类型仍拒绝。
// data 是当前独立正文，成功后完整替换side，不借用调用方可变字节。
func (side *inferenceChosenSide) UnmarshalJSON(data []byte) error {
	if string(data) == "null" {
		return errors.New("fixed side must be an object")
	}
	type plain inferenceChosenSide
	value := plain{jobFixed: jobFixed{Level: 50}}
	if err := json.Unmarshal(data, &value); err != nil {
		return err
	}
	var raw struct {
		Level json.RawMessage `json:"level"`
	}
	if err := json.Unmarshal(data, &raw); err != nil {
		return err
	}
	if string(raw.Level) == "null" {
		return errors.New("level must be an integer")
	}
	*side = inferenceChosenSide(value)
	return nil
}

// validate 只实施原FixedBattleSideSelection/请求的边界约束，不裁定机制支持或计算能力。
// 返回值为原稳定业务诊断；任何非法输入都不会被修正后继续求解。
func (side inferenceChosenSide) validate() error {
	if side.PokemonID <= 0 {
		return errors.New("pokemon_id must be a positive integer")
	}
	if side.FormID != nil {
		return errors.New("form_id is not accepted yet; select the form-specific pokemon_id")
	}
	if side.Level < 1 || side.Level > 100 {
		return errors.New("level must be between 1 and 100")
	}
	if side.Profile == "" || side.Profile != strings.TrimSpace(side.Profile) {
		return errors.New("stat_profile_id must be a normalized non-empty string")
	}
	if side.Ability == "" || side.Ability != strings.TrimSpace(side.Ability) {
		return errors.New("ability_identifier must be a normalized non-empty string")
	}
	if side.Item != nil && (*side.Item == "" || *side.Item != strings.TrimSpace(*side.Item)) {
		return errors.New("item_identifier must be normalized when it is provided")
	}
	if len(side.Moves) < 1 || len(side.Moves) > 4 {
		return errors.New("move_ids must contain one to four moves")
	}
	seen := make(map[int]bool, len(side.Moves))
	for _, id := range side.Moves {
		if id <= 0 {
			return errors.New("move_ids must contain positive integers")
		}
		if seen[id] {
			return errors.New("move_ids must be unique")
		}
		seen[id] = true
	}
	return nil
}

// inferenceLimits 是原同步固定图预算；与持久job的2M/8M上限和默认分开保存。
type inferenceLimits struct {
	Nodes int `json:"max_nodes"`
	Edges int `json:"max_edges"`
	Turns int `json:"max_turns"`
}

// defaultInferenceLimits 返回原HTTP默认值，每次调用拥有独立值。
func defaultInferenceLimits() inferenceLimits { return inferenceLimits{50000, 300000, 20} }

// UnmarshalJSON 为data省略字段保留原默认；null预算不等价于未提供或无限。
func (limits *inferenceLimits) UnmarshalJSON(data []byte) error {
	if string(data) == "null" {
		return errors.New("limits must be an object")
	}
	type plain inferenceLimits
	value := plain(defaultInferenceLimits())
	if err := json.Unmarshal(data, &value); err != nil {
		return err
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(data, &fields); err != nil {
		return err
	}
	for _, name := range []string{"max_nodes", "max_edges", "max_turns"} {
		if string(fields[name]) == "null" {
			return errors.New("graph limits must be integers")
		}
	}
	*limits = inferenceLimits(value)
	return nil
}

// inferenceFixedRequest 对应原fixed-one-on-one/graph/step共同的固定输入，不接受任意Core JSON。
type inferenceFixedRequest struct {
	Ruleset        string               `json:"ruleset_id"`
	Version        int                  `json:"version_group_id"`
	Attacker       *inferenceChosenSide `json:"attacker"`
	Defender       *inferenceChosenSide `json:"defender"`
	AttackerPolicy string               `json:"attacker_policy"`
	DefenderPolicy string               `json:"defender_policy"`
	Limits         inferenceLimits      `json:"limits"`
}

// UnmarshalJSON 应用原HTTP省略默认，显式null不能悄悄恢复规则/策略默认值。
// data只在当前请求解码期间借用，成功后request取得完整独立值。
func (request *inferenceFixedRequest) UnmarshalJSON(data []byte) error {
	if string(data) == "null" {
		return errors.New("fixed inference request must be an object")
	}
	type plain inferenceFixedRequest
	value := plain{Ruleset: "pokemon-champion", Version: 25, AttackerPolicy: "uniform-random", DefenderPolicy: "uniform-random", Limits: defaultInferenceLimits()}
	if err := json.Unmarshal(data, &value); err != nil {
		return err
	}
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(data, &raw); err != nil {
		return err
	}
	for _, name := range []string{"ruleset_id", "version_group_id", "attacker_policy", "defender_policy"} {
		if string(raw[name]) == "null" {
			return errors.New("fixed inference identities must not be null")
		}
	}
	*request = inferenceFixedRequest(value)
	return nil
}

// validate 保持原同步路由的规则/等级/策略/预算边界；机制准入留给Core。
func (request inferenceFixedRequest) validate() error {
	if request.Attacker == nil || request.Defender == nil {
		return errors.New("attacker and defender are required")
	}
	for _, side := range []*inferenceChosenSide{request.Attacker, request.Defender} {
		if err := side.validate(); err != nil {
			return err
		}
	}
	if request.Attacker.Level != request.Defender.Level {
		return errors.New("both sides must use the same level in v1")
	}
	if request.Ruleset == "" || request.Ruleset != strings.TrimSpace(request.Ruleset) {
		return errors.New("ruleset_id must be a non-empty normalized identifier")
	}
	if request.Version <= 0 {
		return errors.New("version_group_id must be greater than 0")
	}
	for _, policy := range []string{request.AttackerPolicy, request.DefenderPolicy} {
		if policy != "uniform-random" && policy != "first-legal" {
			return errors.New("unsupported battle action policy")
		}
	}
	if request.Limits.Nodes < 1 || request.Limits.Nodes > 500000 || request.Limits.Edges < 1 || request.Limits.Edges > 2000000 || request.Limits.Turns < 1 || request.Limits.Turns > 200 {
		return errors.New("fixed battle graph limits are out of range")
	}
	return nil
}

// inferencePolicy 只转换两个既有协议字符串；调用前已验证，不推导选招分布。
func inferencePolicy(policy string) string {
	if policy == "first-legal" {
		return "first-legal-action"
	}
	return policy
}
