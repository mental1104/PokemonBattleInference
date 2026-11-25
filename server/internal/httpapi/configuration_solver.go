package httpapi

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"pokemonbattleinference/server/internal/catalog"
	"time"
)

// configurationSolverHandler 负责原HTTP/知识/展示编排；模板、目标、严格速度和EV/IV搜索只由Core执行。
type configurationSolverHandler struct {
	store  *catalog.Store
	core   calculatorHandler
	search bool
}

// registerConfigurationSolver 挂接两个原WithSpeed入口；不以单次damage或CoreJSON替代原业务请求。
func registerConfigurationSolver(mux *http.ServeMux, db *sql.DB) {
	store, core := catalog.New(db), calculatorHandler{worker: configuredWorker()}
	mux.Handle("POST /v1/configuration_solver/solve", configurationSolverHandler{store, core, false})
	mux.Handle("POST /v1/configuration_solver/search-spreads", configurationSolverHandler{store, core, true})
}

// ServeHTTP 在共享30秒ctx下冻结完整资料/准备目标并求解；schema错误422、原应用输入错误400。
func (handler configurationSolverHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	maximum := 3
	if handler.search {
		maximum = 10
	}
	input := solverInput{search: handler.search, Ruleset: "pokemon-champion", Level: 50, Maximum: maximum, Goals: []solverGoalInput{}, Speed: []solverSpeedInput{}, Allowed: []string{}}
	decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 8<<20))
	if decoder.Decode(&input) != nil {
		detail(w, 422, "invalid configuration solver request")
		return
	}
	var extra any
	if decoder.Decode(&extra) != io.EOF || !input.validateSchema() {
		detail(w, 422, "invalid configuration solver fields")
		return
	}
	if handler.search {
		input.Allowed = nil
	} // 原search schema忽略这一额外字段，不把模板限制引入EV搜索。
	if err := input.validateApplication(); err != nil {
		detail(w, 400, err.Error())
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), 30*time.Second)
	defer cancel()
	pokemonIDs := []int{*input.Subject}
	moveIDs := []int{}
	for _, goal := range input.Goals {
		pokemonIDs = append(pokemonIDs, *goal.Target)
		moveIDs = append(moveIDs, *goal.Move)
	}
	for _, goal := range input.Speed {
		pokemonIDs = append(pokemonIDs, *goal.Target)
	}
	snapshot, err := handler.store.Goals(ctx, input.Ruleset, pokemonIDs, moveIDs)
	if err != nil {
		var invalid *catalog.CalculationInputError
		if errors.As(err, &invalid) || ctx.Err() != nil {
			calculatorFailure(w, err)
		} else {
			detail(w, 503, "catalog storage unavailable")
		}
		return
	}
	prepared, err := handler.prepare(ctx, input, snapshot)
	if err != nil {
		calculatorFailure(w, err)
		return
	}
	results, err := handler.core.batch(ctx, []any{prepared.Operation})
	if err != nil {
		calculatorFailure(w, err)
		return
	}
	var result solverNativeResult
	if json.Unmarshal(results[0], &result) != nil || result.Kind != prepared.Operation["kind"] {
		detail(w, 500, "invalid native solver response")
		return
	}
	response, err := handler.response(input, prepared, result)
	if err != nil {
		detail(w, 500, "invalid native solver evidence")
		return
	}
	writeJSON(w, 200, response)
}

// solverPokemonSummary 只投影同一快照的原公开展示字段，不重查名称或合并形态。
func solverPokemonSummary(pokemon catalog.GoalPokemon, ruleset string) any {
	return map[string]any{"pokemon_id": pokemon.ID, "identifier": pokemon.Identifier, "display_name": pokemon.Name, "form_identifier": pokemon.Form, "sprite_url": fmt.Sprintf("/api/v1/assets/pokemon/%d/sprite?ruleset_id=%s&slot=front_default", pokemon.ID, ruleset), "types": pokemon.TypeIdentifiers, "type_names": pokemon.TypeNames}
}

// solverGoalViews 把Core目标证据与对应原资料连接；伤害范围只取Core有序rolls两端，不重算伤害或目标满足性。
func solverGoalViews(input solverInput, snapshot catalog.GoalSnapshot, goals []solverNativeGoal) ([]any, error) {
	views := []any{}
	for _, evidence := range goals {
		var requested *solverGoalInput
		for index := range input.Goals {
			if *input.Goals[index].ID == evidence.ID {
				requested = &input.Goals[index]
				break
			}
		}
		if requested == nil || len(evidence.Damage.Rolls) == 0 {
			return nil, fmt.Errorf("native goal has no owning request or damage rolls")
		}
		move := snapshot.Moves[*requested.Move]
		moveView := map[string]any{"move_id": move.ID, "identifier": move.Identifier, "display_name": move.Name, "type": move.TypeIdentifier, "type_name": move.TypeName, "category": move.Category, "power": move.Power}
		views = append(views, map[string]any{"goal_id": evidence.ID, "kind": evidence.Kind, "satisfied": evidence.Satisfied, "subject_role": evidence.Role, "target": solverPokemonSummary(snapshot.Pokemon[*requested.Target], input.Ruleset), "move": moveView, "roll_policy": evidence.Roll, "damage_min": evidence.Damage.Rolls[0], "damage_max": evidence.Damage.Rolls[len(evidence.Damage.Rolls)-1], "selected_damage": evidence.Selected, "repetitions": evidence.Repetitions, "total_damage": json.Number(evidence.Total), "hp_threshold": evidence.Threshold, "remaining_hp": json.Number(evidence.Remaining), "effective_attack": evidence.Attack, "effective_defense": evidence.Defense})
	}
	return views, nil
}

// solverSpeedViews 使用Core原satisfied/Speed/margin，仅补同知识快照中的目标展示。
func solverSpeedViews(input solverInput, snapshot catalog.GoalSnapshot, goals []solverNativeSpeed) ([]any, error) {
	views := []any{}
	for _, evidence := range goals {
		var requested *solverSpeedInput
		for index := range input.Speed {
			if *input.Speed[index].ID == evidence.ID {
				requested = &input.Speed[index]
				break
			}
		}
		if requested == nil {
			return nil, fmt.Errorf("native speed goal has no owning request")
		}
		views = append(views, map[string]any{"goal_id": evidence.ID, "satisfied": evidence.Satisfied, "target": solverPokemonSummary(snapshot.Pokemon[*requested.Target], input.Ruleset), "subject_speed": evidence.Subject, "target_speed": evidence.Target, "speed_margin": evidence.Margin})
	}
	return views, nil
}

// solverRanges 把Core六顺序区间改为原HTTP字段名，保留独立范围含义，不组合或扩张范围。
func solverRanges(ranges []json.RawMessage) (any, error) {
	if len(ranges) != 6 {
		return nil, fmt.Errorf("native solver ranges must contain six fields")
	}
	result := map[string]json.RawMessage{}
	for index, name := range []string{"hp", "attack", "defense", "special_attack", "special_defense", "speed"} {
		result[name] = ranges[index]
	}
	return result, nil
}

// response 为所有Core候选/首失败证据补原metadata；scope/warnings仅是已声明HTTP能力说明，不更改计算结果。
func (handler configurationSolverHandler) response(input solverInput, prepared solverPrepared, result solverNativeResult) (any, error) {
	candidates := []any{}
	for _, candidate := range result.Candidates {
		goals, err := solverGoalViews(input, prepared.Snapshot, candidate.Goals)
		if err != nil {
			return nil, err
		}
		speeds, err := solverSpeedViews(input, prepared.Snapshot, candidate.Speed)
		if err != nil {
			return nil, err
		}
		view := map[string]any{"stat_preset": candidate.Preset, "stats": candidate.Stats, "goals": goals, "speed_goals": speeds, "solution_kind": "preset", "nature_id": nil, "nature_label": nil, "nature_options": []any{}, "evs": nil, "ivs": nil, "ev_ranges": nil, "iv_ranges": nil}
		if !handler.search {
			profile, exists := prepared.Profiles[candidate.Preset]
			if !exists {
				return nil, fmt.Errorf("native candidate has no template metadata")
			}
			view["stat_preset_label"], view["stat_preset_assumption"] = profile.View.Label, profile.View.Assumption
		} else {
			evRanges, err := solverRanges(candidate.EVRanges)
			if err != nil {
				return nil, err
			}
			ivRanges, err := solverRanges(candidate.IVRanges)
			if err != nil {
				return nil, err
			}
			// EV总和只用于原标签展示；配置选择/510过滤/排序/区间均已由Core完成。
			evTotal := candidate.EVs.HP + candidate.EVs.Attack + candidate.EVs.Defense + candidate.EVs.SpecialAttack + candidate.EVs.SpecialDefense + candidate.EVs.Speed
			view["stat_preset"], view["stat_preset_label"] = candidate.ID, fmt.Sprintf("反推解 · %s · EV %d", candidate.NatureLabel, evTotal)
			view["stat_preset_assumption"] = "代表值满足全部目标；区间表示其余五项保持代表值时，该字段可独立调整。"
			view["solution_kind"], view["nature_id"], view["nature_label"], view["nature_options"] = "spread", candidate.Nature, candidate.NatureLabel, candidate.NatureOptions
			view["evs"], view["ivs"], view["ev_ranges"], view["iv_ranges"] = candidate.EVs, candidate.IVs, evRanges, ivRanges
		}
		candidates = append(candidates, view)
	}
	rejected, err := solverGoalViews(input, prepared.Snapshot, result.Rejected)
	if err != nil {
		return nil, err
	}
	rejectedSpeed, err := solverSpeedViews(input, prepared.Snapshot, result.RejectedSpeed)
	if err != nil {
		return nil, err
	}
	scope := []string{"同一套配置同时验收全部目标", "EV/性格模板", "严格速度比较", "等级", "已实现持有道具", "已实现特性", "招式固定威力", "STAB", "属性克制", "指定随机伤害档"}
	warnings := append([]string{}, prepared.Warnings...)
	if handler.search {
		scope = []string{"同一套配置同时验收全部目标", "EV/IV/性格反推", "合法 EV 单项与总量约束", "单字段独立安全区间", "严格速度比较", "等级", "已实现持有道具", "已实现特性", "招式固定威力", "STAB", "属性克制", "指定随机伤害档"}
		warnings = append(warnings, "区间表示其余五项保持代表值时，该单项可独立调整的安全范围；不要把六项区间任意组合后仍视为必然可达。")
		if len(input.Speed) == 0 {
			warnings = append(warnings, "当前目标不约束速度；代表解默认 Speed EV 为 0，Speed IV 为 31。")
		}
	}
	if !handler.search || len(input.Speed) > 0 {
		warnings = append(warnings, "速度目标按实际 Speed 严格大于目标配置判定；同速不满足。", "当前速度目标不计入战斗中的速度等级、天气、特性或道具速度修正。")
	}
	if handler.search {
		warnings = append(warnings, "未自动放宽目标；不可达表示合法 EV 总量与当前机制范围内没有配置满足全部约束。")
	} else {
		warnings = append(warnings, "未自动放宽目标；不可达表示当前搜索空间内没有配置满足全部约束。")
	}
	return map[string]any{"ruleset_id": input.Ruleset, "ruleset_name": prepared.Snapshot.Rules.Name, "subject": solverPokemonSummary(prepared.Snapshot.Pokemon[*input.Subject], input.Ruleset), "level": input.Level, "reachable": result.Reachable, "candidates": candidates, "rejected_goals": rejected, "rejected_speed_goals": rejectedSpeed, "scope": scope, "warnings": warnings}, nil
}
