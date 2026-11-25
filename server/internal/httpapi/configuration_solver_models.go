package httpapi

import (
	"encoding/json"
	"errors"
	"fmt"
	"pokemonbattleinference/server/internal/configurations"
	"strings"
)

// solverGoalInput 保存原伤害目标；指针区分必填缺失，省略次数/目标模板沿用原默认。
type solverGoalInput struct {
	ID      *string `json:"goal_id"`
	Kind    *string `json:"kind"`
	Target  *int    `json:"target_pokemon_id"`
	Move    *int    `json:"move_id"`
	Turns   int     `json:"required_turns"`
	Ability *string `json:"target_ability_identifier"`
	Item    *string `json:"target_item_identifier"`
	Profile string  `json:"target_stat_preset"`
	Roll    *string `json:"damage_roll_policy"`
}

// UnmarshalJSON 为data中省略的次数/模板补原默认；未知字段按原BaseModel忽略，显式null非可选字段拒绝。
func (goal *solverGoalInput) UnmarshalJSON(data []byte) error {
	type plain solverGoalInput
	value := plain{Turns: 1, Profile: "no_investment"}
	if err := json.Unmarshal(data, &value); err != nil {
		return err
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(data, &fields); err != nil {
		return err
	}
	for _, name := range []string{"required_turns", "target_stat_preset"} {
		if string(fields[name]) == "null" {
			return errors.New("goal fields must not be null")
		}
	}
	*goal = solverGoalInput(value)
	return nil
}

// solverSpeedInput 是原严格速度线请求；目标实际Speed只允许由Core计算。
type solverSpeedInput struct {
	ID      *string `json:"goal_id"`
	Target  *int    `json:"target_pokemon_id"`
	Profile *string `json:"target_stat_preset"`
}

// solverInput 是两个原WithSpeed入口的共用传输模型；默认候选数由所选路由设置。
type solverInput struct {
	search  bool
	Ruleset string             `json:"ruleset_id"`
	Subject *int               `json:"subject_pokemon_id"`
	Ability *string            `json:"subject_ability_identifier"`
	Item    *string            `json:"subject_item_identifier"`
	Level   int                `json:"level"`
	Goals   []solverGoalInput  `json:"goals"`
	Speed   []solverSpeedInput `json:"speed_goals"`
	Allowed []string           `json:"allowed_stat_presets"`
	Maximum int                `json:"max_candidates"`
}

// UnmarshalJSON 保留调用方设置的solve/search各自默认；拒绝原schema非nullable字段的null，不拒绝额外字段。
func (input *solverInput) UnmarshalJSON(data []byte) error {
	type plain solverInput
	value := plain(*input)
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(data, &fields); err != nil {
		return err
	}
	if input.search {
		// 原search schema没有此字段，任意额外值都应忽略，不能先按solve的list类型拒绝。
		delete(fields, "allowed_stat_presets")
		var err error
		data, err = json.Marshal(fields)
		if err != nil {
			return err
		}
	}
	if err := json.Unmarshal(data, &value); err != nil {
		return err
	}
	for _, name := range []string{"ruleset_id", "level", "goals", "speed_goals", "allowed_stat_presets", "max_candidates"} {
		if string(fields[name]) == "null" {
			return errors.New("solver fields must not be null")
		}
	}
	*input = solverInput(value)
	return nil
}

// validateSchema 只检查原HTTP字段/范围；返回false表示422，不执行目标数学或选择候选。
func (input solverInput) validateSchema() bool {
	if input.Subject == nil || *input.Subject <= 0 || input.Ability == nil || *input.Ability == "" || input.Level < 1 || input.Level > 100 || input.Maximum < 1 || input.Maximum > 10 || len(input.Goals) > 20 || len(input.Speed) > 20 {
		return false
	}
	for _, goal := range input.Goals {
		if goal.ID == nil || goal.Kind == nil || (*goal.Kind != "attack" && *goal.Kind != "defense") || goal.Target == nil || *goal.Target <= 0 || goal.Move == nil || *goal.Move <= 0 || goal.Ability == nil || *goal.Ability == "" || goal.Turns < 1 || goal.Turns > 10 || goal.Roll != nil && *goal.Roll != "min" && *goal.Roll != "max" {
			return false
		}
	}
	for _, goal := range input.Speed {
		if goal.ID == nil || goal.Target == nil || *goal.Target <= 0 || goal.Profile == nil || *goal.Profile == "" {
			return false
		}
	}
	return true
}

// validateApplication 保留原空目标/跨类型重复ID的400错误；能力/速度/目标阈值判断仍由Core完成。
func (input solverInput) validateApplication() error {
	if strings.TrimSpace(*input.Ability) == "" {
		return errors.New("subject_ability_identifier is required")
	}
	if len(input.Goals) == 0 && len(input.Speed) == 0 {
		return errors.New("at least one goal is required")
	}
	seen := map[string]bool{}
	for _, goal := range input.Goals {
		if *goal.ID == "" || *goal.ID != strings.TrimSpace(*goal.ID) {
			return errors.New("goal_id must be a normalized non-empty string")
		}
		if seen[*goal.ID] {
			return fmt.Errorf("duplicate goal_id: %s", *goal.ID)
		}
		seen[*goal.ID] = true
		if strings.TrimSpace(*goal.Ability) == "" {
			return errors.New("target_ability_identifier is required")
		}
	}
	for _, goal := range input.Speed {
		if seen[*goal.ID] {
			return fmt.Errorf("duplicate goal_id: %s", *goal.ID)
		}
		seen[*goal.ID] = true
		if *goal.ID == "" || *goal.ID != strings.TrimSpace(*goal.ID) {
			return errors.New("speed goal_id must be a normalized non-empty string")
		}
		if strings.TrimSpace(*goal.Profile) == "" {
			return errors.New("speed target_stat_preset is required")
		}
	}
	return nil
}

// solverNativeGoal 保留Core的全部目标证据，任意精度累计伤害以十进制字符串进入传输层。
type solverNativeGoal struct {
	ID        string `json:"goal_id"`
	Kind      string `json:"kind"`
	Role      string `json:"subject_role"`
	Satisfied bool   `json:"satisfied"`
	Damage    struct {
		Rolls []int `json:"rolls"`
	} `json:"damage"`
	Selected    int    `json:"selected_damage"`
	Repetitions int    `json:"repetitions"`
	Total       string `json:"total_damage"`
	Threshold   int    `json:"hp_threshold"`
	Remaining   string `json:"remaining_hp"`
	Attack      *int   `json:"effective_attack"`
	Defense     *int   `json:"effective_defense"`
	Roll        string `json:"roll_policy"`
}

// solverNativeSpeed 是Core真实比较后的速度证据；Go不重算margin或satisfied。
type solverNativeSpeed struct {
	ID        string `json:"goal_id"`
	Satisfied bool   `json:"satisfied"`
	Subject   int    `json:"subject_speed"`
	Target    int    `json:"target_speed"`
	Margin    int    `json:"speed_margin"`
}

// solverNativeCandidate 同时接收模板或EV搜索的拥有结果；区间固定六顺序，展示时只做字段投影。
type solverNativeCandidate struct {
	Preset        string                `json:"preset_key"`
	ID            string                `json:"candidate_id"`
	Nature        string                `json:"nature_id"`
	NatureLabel   string                `json:"nature_label"`
	NatureOptions json.RawMessage       `json:"nature_options"`
	Stats         configurations.Spread `json:"stats"`
	EVs           configurations.Spread `json:"evs"`
	IVs           configurations.Spread `json:"ivs"`
	EVRanges      []json.RawMessage     `json:"ev_ranges"`
	IVRanges      []json.RawMessage     `json:"iv_ranges"`
	Goals         []solverNativeGoal    `json:"goals"`
	Speed         []solverNativeSpeed   `json:"speed_goals"`
}

// solverNativeResult 是正式.8两操作的结果，不把缺结果或部分错误改写成不可达成功。
type solverNativeResult struct {
	Kind          string                  `json:"kind"`
	Reachable     bool                    `json:"reachable"`
	Candidates    []solverNativeCandidate `json:"candidates"`
	Rejected      []solverNativeGoal      `json:"rejected_goals"`
	RejectedSpeed []solverNativeSpeed     `json:"rejected_speed_goals"`
}
