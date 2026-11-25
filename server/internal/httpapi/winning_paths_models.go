package httpapi

import "encoding/json"

// winningConfigurationSide 是Core给出的根配置摘要，所有整数只做无损JSON数字转写，不重新算状态。
type winningConfigurationSide struct {
	PokemonID json.Number   `json:"pokemon_id"`
	Name      string        `json:"name"`
	Level     json.Number   `json:"level"`
	Ability   string        `json:"ability_identifier"`
	Item      string        `json:"item_identifier"`
	Moves     []json.Number `json:"move_ids"`
}

// winningConfiguration 保留Core生成的完整配置身份，不能由Go挑选技能或重新计算SHA。
type winningConfiguration struct {
	Key      string                   `json:"configuration_key"`
	Attacker winningConfigurationSide `json:"attacker"`
	Defender winningConfigurationSide `json:"defender"`
}

// winningActionAlternative 保留原事件解释的双方联合行动；没有选择时对应字段必须null。
type winningActionAlternative struct {
	AttackerMove   *json.Number `json:"attacker_move_id"`
	DefenderMove   *json.Number `json:"defender_move_id"`
	AttackerSource *string      `json:"attacker_source_identifier"`
	DefenderSource *string      `json:"defender_source_identifier"`
}

// winningActionStep 是Core按真实事件归并出的一个行动步骤，平台不提取或排序alternatives。
type winningActionStep struct {
	Turn json.Number `json:"turn_number"`
	winningActionAlternative
	Ambiguous    bool                       `json:"ambiguous"`
	Alternatives []winningActionAlternative `json:"alternatives"`
}

// winningKeyEvent 无损转发Core挑选的关键结构化事件；没有actor/target/value时保留null。
type winningKeyEvent struct {
	Kind   string       `json:"kind"`
	Actor  *string      `json:"actor"`
	Target *string      `json:"target"`
	Move   *json.Number `json:"move_id"`
	Source *string      `json:"source_identifier"`
}

// winningPathGroup 是Core完整归并结果，整数路径数/ID/HP不经float64或int64中转。
type winningPathGroup struct {
	Key            string               `json:"path_key"`
	TerminalTurn   json.Number          `json:"terminal_turn"`
	Probability    inferenceProbability `json:"probability"`
	RawPaths       json.Number          `json:"raw_path_count"`
	RawHistories   json.Number          `json:"raw_history_count_estimate"`
	Reasons        []string             `json:"terminal_reasons"`
	TerminalNodes  []json.Number        `json:"terminal_node_ids"`
	Actions        []winningActionStep  `json:"actions"`
	Representative []inferenceGraphStep `json:"representative_path"`
	Damages        []json.Number        `json:"damage_values"`
	AttackerHP     []json.Number        `json:"attacker_remaining_hp_values"`
	DefenderHP     []json.Number        `json:"defender_remaining_hp_values"`
	Events         []winningKeyEvent    `json:"key_events"`
}

// winningPrefixNode 原样保留Core已完成的前缀树、精确概率及排序，递归只用于JSON编解码。
type winningPrefixNode struct {
	Key         string               `json:"prefix_key"`
	Depth       json.Number          `json:"depth"`
	Action      *winningActionStep   `json:"action"`
	Probability inferenceProbability `json:"probability"`
	RawPaths    json.Number          `json:"raw_path_count"`
	Terminals   []string             `json:"terminal_path_keys"`
	Children    []winningPrefixNode  `json:"children"`
}

// winningCycleReference 是Core检测出的原回边引用；缺component时null，平台不补SCC。
type winningCycleReference struct {
	Source    json.Number  `json:"source_node_id"`
	Edge      json.Number  `json:"edge_id"`
	Target    json.Number  `json:"target_node_id"`
	Depth     json.Number  `json:"prefix_depth"`
	Component *json.Number `json:"component_id"`
}

// winningPathsResponse 只负责旧HTTP DTO及整数传输形状；概率分子/分母保持原字符串。
type winningPathsResponse struct {
	ID                  string                  `json:"graph_id"`
	Revision            string                  `json:"calculation_revision"`
	Winner              string                  `json:"winner"`
	Sort                string                  `json:"sort"`
	Configuration       winningConfiguration    `json:"configuration"`
	WinnerProbability   *inferenceProbability   `json:"winner_probability"`
	ReturnedProbability inferenceProbability    `json:"returned_probability"`
	Coverage            *inferenceProbability   `json:"returned_coverage"`
	Groups              []winningPathGroup      `json:"path_groups"`
	Prefix              winningPrefixNode       `json:"prefix_tree"`
	Cycles              []winningCycleReference `json:"cycle_references"`
	Next                *string                 `json:"next_cursor"`
	More                bool                    `json:"has_more"`
	Complete            bool                    `json:"query_complete"`
	Truncated           bool                    `json:"traversal_truncated"`
}
