package httpapi

import (
	"encoding/json"
	"errors"
	"math/big"
	"pokemonbattleinference/server/internal/configurations"
)

// inferenceProbability 保留原字符串精确分数，decimal/percent只用于原HTTP展示。
type inferenceProbability struct {
	Numerator   string  `json:"numerator"`
	Denominator string  `json:"denominator"`
	Decimal     float64 `json:"decimal"`
	Percent     float64 `json:"percent"`
}

// inferenceExpected 保持原任意精度JSON整数/null合同，不把无限期望写成零。
type inferenceExpected struct {
	Available   bool         `json:"available"`
	Numerator   *json.Number `json:"numerator"`
	Denominator *json.Number `json:"denominator"`
	Decimal     *float64     `json:"decimal"`
}

// inferencePokemonSummary 是Core已计算实际能力和规范招式的HTTP解释投影。
type inferencePokemonSummary struct {
	ID      int                   `json:"pokemon_id"`
	Name    string                `json:"name"`
	Level   int                   `json:"level"`
	Ability string                `json:"ability_identifier"`
	Item    string                `json:"item_identifier"`
	Moves   []int                 `json:"move_ids"`
	Names   []string              `json:"move_names"`
	Stats   configurations.Spread `json:"stats"`
	Labels  map[string]string     `json:"dimension_labels"`
}

// inferenceGraphSummary 只读取真实Core统计，不从HTTP页数或原始JSON长度估算规模。
type inferenceGraphSummary struct {
	Nodes          int      `json:"unique_state_count"`
	Edges          int      `json:"edge_count"`
	MaxTurn        int      `json:"max_turn_number"`
	Closed         int      `json:"closed_cycle_count"`
	ReachableCycle int      `json:"terminal_reachable_cycle_count"`
	Complete       bool     `json:"is_complete"`
	Truncations    []string `json:"truncation_reasons"`
}

// inferenceCompleteness 保留原solver状态、截断和诊断，warnings不代替成功判定。
type inferenceCompleteness struct {
	GraphComplete bool     `json:"graph_complete"`
	SolverStatus  string   `json:"solver_status"`
	Truncations   []string `json:"truncation_reasons"`
	Diagnostics   []string `json:"diagnostics"`
	Warnings      []string `json:"warnings"`
}

// inferenceSummary 对应原summary-only响应；代表路径明确为空，不凭终局HP捏造路径。
type inferenceSummary struct {
	Ruleset        string                  `json:"ruleset_id"`
	Version        int                     `json:"version_group_id"`
	Observer       string                  `json:"observer"`
	Attacker       inferencePokemonSummary `json:"attacker"`
	Defender       inferencePokemonSummary `json:"defender"`
	Win            inferenceProbability    `json:"win_probability"`
	Loss           inferenceProbability    `json:"loss_probability"`
	Draw           inferenceProbability    `json:"draw_probability"`
	Expected       inferenceExpected       `json:"expected_turns"`
	AttackerPolicy string                  `json:"attacker_policy"`
	DefenderPolicy string                  `json:"defender_policy"`
	Graph          inferenceGraphSummary   `json:"graph"`
	Paths          []json.RawMessage       `json:"representative_paths"`
	Included       []string                `json:"included_mechanisms"`
	Excluded       []string                `json:"excluded_mechanisms"`
	Coverage       float64                 `json:"configuration_coverage_percent"`
	Completeness   inferenceCompleteness   `json:"completeness"`
}

// inferenceNativeResult 解码正式fixed_battle完整摘要，概率空值保持失败而非默认为零。
type inferenceNativeResult struct {
	Kind        string              `json:"kind"`
	Observer    string              `json:"observer"`
	Status      string              `json:"status"`
	Win         *calculatorFraction `json:"win"`
	Loss        *calculatorFraction `json:"loss"`
	Draw        *calculatorFraction `json:"draw"`
	Truncations []string            `json:"truncations"`
	Diagnostics []string            `json:"diagnostics"`
	Statistics  struct {
		Nodes          int `json:"nodes"`
		Edges          int `json:"edges"`
		MaxTurn        int `json:"max_turn_number"`
		Closed         int `json:"closed_cycles"`
		ReachableCycle int `json:"terminal_reachable_cycles"`
	} `json:"statistics"`
	Expected struct {
		Status string              `json:"status"`
		Value  *calculatorFraction `json:"value"`
	} `json:"expected_turns"`
	Graph json.RawMessage               `json:"graph"`
	Paths []inferenceRepresentativePath `json:"representative_paths"`
}

// inferenceDisplayProbability 将Core分数转换为原展示DTO；任何缺失/非法分母明确失败。
func inferenceDisplayProbability(value *calculatorFraction) (inferenceProbability, error) {
	if value == nil {
		return inferenceProbability{}, errors.New("native inference omitted a solved probability")
	}
	decimal, err := value.probability()
	if err != nil {
		return inferenceProbability{}, err
	}
	return inferenceProbability{value.Numerator, value.Denominator, decimal, decimal * 100}, nil
}

// inferenceDisplayExpected 只变换HTTP数值表示；无限期望available=false，有限值不窄化为int64。
func inferenceDisplayExpected(status string, value *calculatorFraction) (inferenceExpected, error) {
	if status == "infinite" {
		return inferenceExpected{}, nil
	}
	if status != "finite" || value == nil {
		return inferenceExpected{}, errors.New("native solved inference omitted expected turns")
	}
	ratio, ok := new(big.Rat).SetString(value.Numerator + "/" + value.Denominator)
	if !ok || ratio.Sign() < 0 {
		return inferenceExpected{}, errors.New("invalid native expected turns")
	}
	numerator, denominator := json.Number(value.Numerator), json.Number(value.Denominator)
	decimal, _ := ratio.Float64()
	return inferenceExpected{true, &numerator, &denominator, &decimal}, nil
}
