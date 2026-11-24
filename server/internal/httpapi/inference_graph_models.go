package httpapi

import "encoding/json"

// inferenceGraphCursor 只保存原HTTP步骤，不把节点代表前驱当成用户的实际路径。
type inferenceGraphCursor struct {
	Steps []inferenceGraphStep `json:"steps"`
}

// inferenceGraphStep 的三个身份都是无损JSON整数，可表达snapshot第五层以后的任意精度ID。
type inferenceGraphStep struct {
	Source json.Number `json:"source_node_id"`
	Edge   json.Number `json:"edge_id"`
	Target json.Number `json:"target_node_id"`
}

// inferenceMoveSlot 是Core已验证的槽位展示，不在Go推导PP或讲究锁招。
type inferenceMoveSlot struct {
	MoveID   int  `json:"move_id"`
	PP       int  `json:"current_pp"`
	MaxPP    int  `json:"max_pp"`
	Disabled bool `json:"disabled"`
	Locked   bool `json:"locked"`
}

// inferenceStatusDetail 保留原状态的四项可空计数/来源，不把缺失字段补为零。
type inferenceStatusDetail struct {
	Kind      string  `json:"kind"`
	Asleep    *int    `json:"turns_asleep"`
	Toxic     *int    `json:"toxic_counter"`
	Remaining *int    `json:"turns_remaining"`
	Source    *string `json:"source_id"`
}

// inferenceStageDetail 是Core状态的七个原等级字段，Go不计算实际速度或伤害。
type inferenceStageDetail struct {
	Attack         int `json:"attack"`
	Defense        int `json:"defense"`
	SpecialAttack  int `json:"special_attack"`
	SpecialDefense int `json:"special_defense"`
	Speed          int `json:"speed"`
	Accuracy       int `json:"accuracy"`
	Evasion        int `json:"evasion"`
}

// inferenceBattlerDetail 完整转发Core节点的一侧动态事实；JSON空状态保持null。
type inferenceBattlerDetail struct {
	PokemonID  int                     `json:"pokemon_id"`
	Name       string                  `json:"name"`
	Ability    string                  `json:"ability"`
	Item       string                  `json:"item"`
	HP         int                     `json:"current_hp"`
	MaxHP      int                     `json:"max_hp"`
	Moves      []inferenceMoveSlot     `json:"moves"`
	Major      *inferenceStatusDetail  `json:"major_status"`
	Volatile   []inferenceStatusDetail `json:"volatile_statuses"`
	Stages     inferenceStageDetail    `json:"stat_stages"`
	LastMove   *int                    `json:"last_move_id"`
	ChoiceLock *int                    `json:"choice_lock_move_id"`
	Consumed   bool                    `json:"item_consumed"`
	FirstTurn  bool                    `json:"first_turn"`
}

// inferenceSideConditions 保留各自屏障事实，不在传输层合并或互斥化。
type inferenceSideConditions struct {
	Reflect     bool `json:"reflect"`
	LightScreen bool `json:"light_screen"`
	AuroraVeil  bool `json:"aurora_veil"`
}

// inferenceFieldDetail 保留天气/场地空值与固定两侧条件，不改变攻击观察方向。
type inferenceFieldDetail struct {
	Weather  *string                 `json:"weather"`
	Terrain  *string                 `json:"terrain"`
	Attacker inferenceSideConditions `json:"attacker_side_conditions"`
	Defender inferenceSideConditions `json:"defender_side_conditions"`
}

// inferenceNodeDetail 是原渐进读取DTO；全部状态和终止语义来自Core。
type inferenceNodeDetail struct {
	ID       json.Number            `json:"node_id"`
	Turn     int                    `json:"turn_number"`
	Phase    string                 `json:"phase"`
	Outcome  string                 `json:"outcome"`
	Reason   *string                `json:"termination_reason"`
	Attacker inferenceBattlerDetail `json:"attacker"`
	Defender inferenceBattlerDetail `json:"defender"`
	Field    inferenceFieldDetail   `json:"field"`
	Terminal bool                   `json:"terminal"`
	Outgoing bool                   `json:"has_outgoing_edges"`
}

// inferenceRandomResult 把ABI十进制数值文本无损解码为原HTTP整数，禁止经过float64。
type inferenceRandomResult struct {
	Type    string       `json:"event_type"`
	ID      string       `json:"event_id"`
	Outcome string       `json:"outcome_id"`
	Value   *json.Number `json:"numeric_value"`
}

// inferenceBattleEvent 保留结构化业务事实和全部可空整数，不解析展示文案恢复语义。
type inferenceBattleEvent struct {
	Kind   string       `json:"kind"`
	Turn   int          `json:"turn_number"`
	Actor  *string      `json:"actor"`
	Target *string      `json:"target"`
	Move   *int         `json:"move_id"`
	Source *string      `json:"source_identifier"`
	Value  *json.Number `json:"value"`
	Before *json.Number `json:"before_value"`
	After  *json.Number `json:"after_value"`
}

// inferenceDamageRoll 的每个档位与实际扣血均为Core原始事实，Go不重新应用倍率。
type inferenceDamageRoll struct {
	Index  int         `json:"raw_roll_index"`
	Roll   json.Number `json:"raw_roll_value"`
	Damage json.Number `json:"final_damage"`
	HPLoss json.Number `json:"actual_hp_loss"`
}

// inferenceEventPath 保留同一正式边全部替代解释，不能只取第一条代表路径。
type inferenceEventPath struct {
	Random []inferenceRandomResult `json:"random_results"`
	Damage []inferenceDamageRoll   `json:"damage_rolls"`
	Battle []inferenceBattleEvent  `json:"battle_events"`
}

// inferenceJointAction 是Core从MOVE_SELECTED事实读取的单侧身份，不是Go规则判断。
type inferenceJointAction struct {
	Side string `json:"side"`
	Type string `json:"action_type"`
	Move *int   `json:"move_id"`
}

// inferenceActionResolution 保留未执行/被阻断/命中可空事实，整数执行顺序无损传输。
type inferenceActionResolution struct {
	Side     string       `json:"side"`
	Type     string       `json:"action_type"`
	Move     *int         `json:"move_id"`
	Position *json.Number `json:"order_position"`
	Status   string       `json:"status"`
	Hit      *bool        `json:"hit"`
	Reason   *string      `json:"reason"`
}

// inferenceStatusEffect 只转发实际施加/阻止事实，不暗示未实现状态门禁已获支持。
type inferenceStatusEffect struct {
	Result     string  `json:"result"`
	SourceSide *string `json:"source_side"`
	TargetSide *string `json:"target_side"`
	Source     *string `json:"source_identifier"`
}

// inferenceCompactResult 保留离散档位集合和原路径计数，不在Go重分组或连成区间。
type inferenceCompactResult struct {
	Target   json.Number                 `json:"target_node_id"`
	Actions  []inferenceActionResolution `json:"action_resolutions"`
	Order    string                      `json:"order_reason"`
	Critical *bool                       `json:"critical_hit"`
	Rolls    []json.Number               `json:"raw_roll_values"`
	Damages  []json.Number               `json:"final_damage_values"`
	Losses   []json.Number               `json:"actual_hp_losses"`
	Effects  []inferenceStatusEffect     `json:"status_effects"`
	Count    int                         `json:"path_count"`
}

// inferenceTransitionLabels 保持Core首次出现顺序，Go不会排序或推导标签来源。
type inferenceTransitionLabels struct {
	Moves   []int    `json:"selected_move_ids"`
	Actors  []string `json:"acting_sides"`
	Targets []string `json:"target_sides"`
	Results []string `json:"result_keys"`
	Sources []string `json:"source_identifiers"`
}

// inferenceTransitionOutcome 只承载Core算出的条件/联合/累计概率和全部后继事实。
type inferenceTransitionOutcome struct {
	Edge        json.Number               `json:"edge_id"`
	Target      json.Number               `json:"target_node_id"`
	Probability inferenceProbability      `json:"probability"`
	Joint       inferenceProbability      `json:"joint_probability"`
	Cumulative  inferenceProbability      `json:"cumulative_probability"`
	Labels      inferenceTransitionLabels `json:"label_fields"`
	Rolls       []json.Number             `json:"raw_random_values"`
	Random      []inferenceRandomResult   `json:"random_results"`
	Damages     []inferenceDamageRoll     `json:"damage_rolls"`
	Compact     []inferenceCompactResult  `json:"compact_results"`
	BattlePaths [][]inferenceBattleEvent  `json:"battle_event_paths"`
	EventPaths  []inferenceEventPath      `json:"event_paths"`
}

// inferenceGroupRange 的空值表示没有合法档位事实，不能变成零伤害范围。
type inferenceGroupRange struct {
	MinimumDamage *json.Number `json:"minimum_damage"`
	MaximumDamage *json.Number `json:"maximum_damage"`
	MinimumLoss   *json.Number `json:"minimum_hp_loss"`
	MaximumLoss   *json.Number `json:"maximum_hp_loss"`
}

// inferenceTransitionGroup 使用Core唯一groupID、选择概率与归并结果，不在Go复制分组算法。
type inferenceTransitionGroup struct {
	ID            string                       `json:"group_id"`
	Kind          string                       `json:"kind"`
	Label         string                       `json:"label_key"`
	Probability   inferenceProbability         `json:"probability"`
	Selection     inferenceProbability         `json:"selection_probability"`
	Attacker      *inferenceJointAction        `json:"attacker_action"`
	Defender      *inferenceJointAction        `json:"defender_action"`
	RawCount      int                          `json:"raw_result_count"`
	DistinctCount int                          `json:"distinct_outcome_count"`
	Summary       inferenceGroupRange          `json:"summary"`
	Expanded      bool                         `json:"expanded"`
	Outcomes      []inferenceTransitionOutcome `json:"outcomes"`
}

// inferenceNodeProjection 对应同Core原application投影，所有整数和空数组按原HTTP形状输出。
type inferenceNodeProjection struct {
	Node       inferenceNodeDetail        `json:"node"`
	Cumulative inferenceProbability       `json:"cumulative_probability"`
	Groups     []inferenceTransitionGroup `json:"transition_groups"`
}

// inferenceReportStep 代表用户实际选中正式边的Core战报一步，不使用代表路径替代。
type inferenceReportStep struct {
	Depth       int                  `json:"depth"`
	Source      json.Number          `json:"source_node_id"`
	Edge        json.Number          `json:"edge_id"`
	Target      json.Number          `json:"target_node_id"`
	Probability inferenceProbability `json:"edge_probability"`
	Cumulative  inferenceProbability `json:"cumulative_probability"`
	Events      []inferenceEventPath `json:"event_paths"`
}

// inferenceBattleReport 是Core逐步结果的线性容器，Go只附加步骤和固定图身份。
type inferenceBattleReport struct {
	GraphID    string                `json:"graph_id"`
	Revision   string                `json:"calculation_revision"`
	Root       json.Number           `json:"root_node_id"`
	Current    json.Number           `json:"current_node_id"`
	Depth      int                   `json:"depth"`
	Cumulative inferenceProbability  `json:"cumulative_probability"`
	Steps      []inferenceReportStep `json:"steps"`
}

// inferenceRepresentativeStep 只转发Core已选择的正式代表节点和首历史标签，不在Go扫描图。
type inferenceRepresentativeStep struct {
	Node       json.Number `json:"node_id"`
	Turn       int         `json:"turn_number"`
	Phase      string      `json:"phase"`
	AttackerHP int         `json:"attacker_hp"`
	DefenderHP int         `json:"defender_hp"`
	Outcome    string      `json:"outcome"`
	Events     []string    `json:"events"`
}

// inferenceRepresentativePath 是Core唯一生成的路径；身份与事件标签保持原HTTP语义。
type inferenceRepresentativePath struct {
	Reference string                        `json:"reference"`
	Outcome   string                        `json:"outcome"`
	Steps     []inferenceRepresentativeStep `json:"steps"`
}

// inferenceExplorationResponse 机械承载Core完整原浏览DTO，不从节点代表前驱生成用户路径。
type inferenceExplorationResponse struct {
	ID          string                     `json:"graph_id"`
	Revision    string                     `json:"calculation_revision"`
	Cursor      inferenceGraphCursor       `json:"cursor"`
	Node        inferenceNodeDetail        `json:"node"`
	Groups      []inferenceTransitionGroup `json:"transition_groups"`
	Cumulative  inferenceProbability       `json:"cumulative_probability"`
	Breadcrumbs []inferenceGraphStep       `json:"breadcrumbs"`
	Report      inferenceBattleReport      `json:"battle_report"`
	Terminal    bool                       `json:"terminal"`
}

// inferenceOutcomesResponse 只转写Core指定原分组和精确概率，完整事件路径不被裁剪。
type inferenceOutcomesResponse struct {
	ID         string                   `json:"graph_id"`
	Revision   string                   `json:"calculation_revision"`
	Cursor     inferenceGraphCursor     `json:"cursor"`
	Current    json.Number              `json:"current_node_id"`
	Cumulative inferenceProbability     `json:"cumulative_probability"`
	Group      inferenceTransitionGroup `json:"transition_group"`
}
