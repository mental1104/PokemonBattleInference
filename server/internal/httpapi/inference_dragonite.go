package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"time"
)

// inferenceDragoniteInput 保留原受控旅程四项选择；这里只是场景配置，不实现特性或回合规则。
type inferenceDragoniteInput struct {
	Ability          string `json:"dragonite_ability"`
	Plan             string `json:"weavile_plan"`
	DragoniteProfile string `json:"dragonite_stat_preset"`
	WeavileProfile   string `json:"weavile_stat_preset"`
}

// UnmarshalJSON 应用原省略默认；显式null仍是格式错误，不能悄悄恢复默认场景。
func (input *inferenceDragoniteInput) UnmarshalJSON(data []byte) error {
	type plain inferenceDragoniteInput
	value := plain{Ability: "multiscale", Plan: "ice-punch", DragoniteProfile: "max_atk_plus", WeavileProfile: "max_atk_plus"}
	if err := json.Unmarshal(data, &value); err != nil {
		return err
	}
	if string(data) == "null" {
		return errors.New("dragonite journey must be an object")
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(data, &fields); err != nil {
		return err
	}
	for _, name := range []string{"dragonite_ability", "weavile_plan", "dragonite_stat_preset", "weavile_stat_preset"} {
		if string(fields[name]) == "null" {
			return errors.New("dragonite journey fields cannot be null")
		}
	}
	*input = inferenceDragoniteInput(value)
	return nil
}

// registerDragoniteJourney 共享唯一graph store，不新增状态服务或后台图缓存。
func registerDragoniteJourney(mux *http.ServeMux, handler inferenceGraphHandler) {
	mux.HandleFunc("POST /v1/inference/dragonite-vs-weavile", handler.dragonite)
}

// inferenceReferenceFailure 保留原旅程的字符串detail，store生命周期错误仍使用原结构化图错误。
func inferenceReferenceFailure(w http.ResponseWriter, err error) {
	var failure *inferenceRequestError
	var graph *inferenceGraphError
	if errors.As(err, &graph) {
		inferenceGraphFailure(w, err)
		return
	}
	if errors.As(err, &failure) {
		detail(w, failure.status, failure.message)
		return
	}
	calculatorFailure(w, err)
}

// dragonite 把原受控场景选择投影成固定配置，再交同一Core reference provider/完整图链。
// ctx贯穿一次PG快照/配置准备/独立child/store；Core拥有透明假设、partial筛选与全部概率/事件。
func (handler inferenceGraphHandler) dragonite(w http.ResponseWriter, r *http.Request) {
	var chosen inferenceDragoniteInput
	if !decodeJSON(w, r, &chosen) {
		return
	}
	if (chosen.Ability != "multiscale" && chosen.Ability != "inner-focus") || (chosen.Plan != "ice-punch" && chosen.Plan != "fake-out-pressure") {
		detail(w, 422, "invalid dragonite journey selection")
		return
	}
	// 这些是原owning router的固定Pokemon/招式/等级选择，玩家选择概率仍由Core策略计算。
	moves := []int{8}
	defenderPolicy := "first-legal"
	if chosen.Plan == "fake-out-pressure" {
		moves = []int{8, 252}
		defenderPolicy = "uniform-random"
	}
	input := inferenceFixedRequest{Ruleset: "pokemon-champion", Version: 25,
		Attacker:       &inferenceChosenSide{jobFixed: jobFixed{PokemonID: 149, Level: 50, Profile: chosen.DragoniteProfile, Ability: chosen.Ability}, Moves: []int{280}},
		Defender:       &inferenceChosenSide{jobFixed: jobFixed{PokemonID: 461, Level: 50, Profile: chosen.WeavileProfile, Ability: "pressure"}, Moves: moves},
		AttackerPolicy: "first-legal", DefenderPolicy: defenderPolicy, Limits: inferenceLimits{Nodes: 20000, Edges: 80000, Turns: 100}}
	ctx, cancel := context.WithTimeout(r.Context(), 30*time.Second)
	defer cancel()
	prepared, err := handler.fixed.prepareReference(ctx, input, jobExecutionBudget{MaxNodes: 20000, MaxEdges: 80000, MaxTurns: &input.Limits.Turns})
	if err != nil {
		inferenceReferenceFailure(w, err)
		return
	}
	result, err := handler.createPrepared(ctx, input, prepared)
	if err != nil {
		inferenceReferenceFailure(w, err)
		return
	}
	writeJSON(w, 200, result)
}
