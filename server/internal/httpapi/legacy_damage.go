package httpapi

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math/big"
	"math/rand/v2"
	"net/http"
	"pokemonbattleinference/server/internal/catalog"
	"pokemonbattleinference/server/internal/configurations"
	"strings"
	"time"
)

// legacyPokemonSelection 保留原可选字段及默认；用户IV只校验原传输类型，不传给历史director计算。
type legacyPokemonSelection struct {
	ID        int      `json:"id"`
	Level     *int64   `json:"level"`
	Basepoint *[]int64 `json:"basepoint"`
	IVs       *[]int64 `json:"individual_values"`
	Nature    *string  `json:"nature"`
}

// defaultLegacyPokemon 返回原独立默认值，避免不同请求共享数组/指针。
func defaultLegacyPokemon() legacyPokemonSelection {
	level, nature := int64(100), "Adamant"
	evs, ivs := []int64{0, 0, 0, 0, 0, 0}, []int64{31, 31, 31, 31, 31, 31}
	return legacyPokemonSelection{Level: &level, Nature: &nature, Basepoint: &evs, IVs: &ivs}
}

// UnmarshalJSON 对data设置原默认并保留nullable字段；显式null对象/id或数组null元素属于原schema错误。
func (pokemon *legacyPokemonSelection) UnmarshalJSON(data []byte) error {
	if string(data) == "null" {
		return errors.New("legacy Pokemon must be an object")
	}
	type plain legacyPokemonSelection
	value := plain(defaultLegacyPokemon())
	if err := json.Unmarshal(data, &value); err != nil {
		return err
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(data, &fields); err != nil {
		return err
	}
	if string(fields["id"]) == "null" {
		return errors.New("legacy id must be an integer")
	}
	for _, field := range []string{"basepoint", "individual_values"} {
		if raw, exists := fields[field]; exists {
			var items []json.RawMessage
			if err := json.Unmarshal(raw, &items); err != nil {
				return err
			}
			for _, item := range items {
				if string(item) == "null" {
					return errors.New("legacy spreads require integer elements")
				}
			}
		}
	}
	*pokemon = legacyPokemonSelection(value)
	return nil
}

// legacyMoveSelection 保留旧自由威力/属性/三种分类，不套用现代move学习池或效果规则。
type legacyMoveSelection struct {
	Power    int64  `json:"power"`
	Category string `json:"move_type"`
	Type     string `json:"type"`
}

// UnmarshalJSON 对data设置40威力/普通物理默认，拒绝原schema非nullable字段null。
func (move *legacyMoveSelection) UnmarshalJSON(data []byte) error {
	if string(data) == "null" {
		return errors.New("legacy move must be an object")
	}
	type plain legacyMoveSelection
	value := plain{Power: 40, Category: "physical_move", Type: "Normal"}
	if err := json.Unmarshal(data, &value); err != nil {
		return err
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(data, &fields); err != nil {
		return err
	}
	for _, name := range []string{"power", "move_type", "type"} {
		if string(fields[name]) == "null" {
			return errors.New("legacy move fields must not be null")
		}
	}
	*move = legacyMoveSelection(value)
	return nil
}

// legacyDamageInput 使用原defenser拼写，不增加公开Core/random/规则集字段；额外字段沿原BaseModel忽略。
type legacyDamageInput struct {
	Attacker legacyPokemonSelection `json:"attacker"`
	Defender legacyPokemonSelection `json:"defenser"`
	Move     legacyMoveSelection    `json:"move"`
}

// UnmarshalJSON 对data中省略的子对象创建原默认实例，不把顶层null当默认请求。
func (input *legacyDamageInput) UnmarshalJSON(data []byte) error {
	if string(data) == "null" {
		return errors.New("legacy damage request must be an object")
	}
	type plain legacyDamageInput
	value := plain{Attacker: defaultLegacyPokemon(), Defender: defaultLegacyPokemon(), Move: legacyMoveSelection{Power: 40, Category: "physical_move", Type: "Normal"}}
	if err := json.Unmarshal(data, &value); err != nil {
		return err
	}
	*input = legacyDamageInput(value)
	return nil
}

// validateSchema 只校验原分类/25性格枚举，不新增现代EV/等级/威力限制。
func (input legacyDamageInput) validateSchema() bool {
	if input.Move.Category != "physical_move" && input.Move.Category != "special_move" && input.Move.Category != "status_move" {
		return false
	}
	for _, pokemon := range []legacyPokemonSelection{input.Attacker, input.Defender} {
		if pokemon.Nature == nil {
			continue
		}
		known := false
		for _, nature := range configurations.Natures() {
			if *pokemon.Nature == nature.Label {
				known = true
				break
			}
		}
		if !known {
			return false
		}
	}
	return true
}

// legacyDamageHandler 只编排全Pokedex知识/原输入/Core/旧DTO；unit是平台随机事实注入点，不含任何领域数学。
type legacyDamageHandler struct {
	store *catalog.Store
	core  calculatorHandler
	unit  func() float64
}

// registerLegacyDamage 挂接旧故障路由的独立算法修复；不将现代damage或500壳当作完成。
func registerLegacyDamage(mux *http.ServeMux, db *sql.DB) {
	mux.Handle("POST /v1/damage", legacyDamageHandler{catalog.New(db), calculatorHandler{worker: configuredWorker()}, rand.Float64})
}

// legacyPokemonNative 只包含历史director真正使用的事实；IV固定31由Core独占处理。
type legacyPokemonNative struct {
	Level     int64    `json:"level"`
	Base      [6]int64 `json:"base"`
	Basepoint []int64  `json:"basepoint"`
	Nature    *string  `json:"nature"`
	Types     []int    `json:"types"`
}

// legacyNativeResult 保留Core任意精度整数字符串；七字段外的准备证据不进入旧HTTP。
type legacyNativeResult struct {
	Kind           string  `json:"kind"`
	Formula        string  `json:"formula"`
	Minimum        string  `json:"min_damage"`
	Maximum        string  `json:"max_damage"`
	Random         string  `json:"random_damage"`
	MinimumPercent float64 `json:"min_damage_percent"`
	MaximumPercent float64 `json:"max_damage_percent"`
	RandomPercent  float64 `json:"random_damage_percent"`
}

// legacyDamageResponse 是原七字段JSON，三个任意精度整数只转换传输表示，不在Go计算。
type legacyDamageResponse struct {
	Formula        string      `json:"formula"`
	Minimum        json.Number `json:"min_damage"`
	Maximum        json.Number `json:"max_damage"`
	Random         json.Number `json:"random_damage"`
	MinimumPercent float64     `json:"min_damage_percent"`
	MaximumPercent float64     `json:"max_damage_percent"`
	RandomPercent  float64     `json:"random_damage_percent"`
}

// ServeHTTP 用同一30秒ctx加载raw双方/属性表，再将原事实和unit交隔离Core；客户端取消同时中断SQL/child。
func (handler legacyDamageHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	var input legacyDamageInput
	decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 8<<20))
	if decoder.Decode(&input) != nil {
		detail(w, 422, "invalid legacy damage request")
		return
	}
	var extra any
	if decoder.Decode(&extra) != io.EOF || !input.validateSchema() {
		detail(w, 422, "invalid legacy damage fields")
		return
	}
	for _, pokemon := range []legacyPokemonSelection{input.Attacker, input.Defender} {
		if pokemon.Level == nil || pokemon.Basepoint == nil {
			detail(w, 400, "legacy level and basepoint must not be null")
			return
		}
	}
	ctx, cancel := context.WithTimeout(r.Context(), 30*time.Second)
	defer cancel()
	snapshot, err := handler.store.LegacyDamage(ctx, input.Attacker.ID, input.Defender.ID)
	if err != nil {
		var invalid *catalog.CalculationInputError
		if errors.As(err, &invalid) || ctx.Err() != nil {
			calculatorFailure(w, err)
		} else {
			detail(w, 503, "legacy catalog storage unavailable")
		}
		return
	}
	moveType, exists := snapshot.TypeNames[strings.ToUpper(input.Move.Type)]
	if !exists {
		detail(w, 400, fmt.Sprintf("%s is not a valid Type", input.Move.Type))
		return
	}
	native := func(selection legacyPokemonSelection, facts catalog.LegacyPokemon) legacyPokemonNative {
		// 只映射原历史构造输入；忽略IV/超过六项EV等数学合同由Core拥有。
		return legacyPokemonNative{*selection.Level, facts.Base, *selection.Basepoint, selection.Nature, facts.Types}
	}
	operation := map[string]any{"kind": "legacy_damage", "attacker": native(input.Attacker, snapshot.Attacker), "defender": native(input.Defender, snapshot.Defender), "move": map[string]any{"power": input.Move.Power, "move_type": input.Move.Category, "type": moveType}, "random_unit": handler.unit(), "type_chart": snapshot.Chart}
	raw, err := handler.core.batch(ctx, []any{operation})
	if err != nil {
		calculatorFailure(w, err)
		return
	}
	var result legacyNativeResult
	if json.Unmarshal(raw[0], &result) != nil || result.Kind != "legacy_damage" {
		detail(w, 500, "invalid native legacy response")
		return
	}
	for _, value := range []string{result.Minimum, result.Maximum, result.Random} {
		integer, ok := new(big.Int).SetString(value, 10)
		if !ok || integer.String() != value {
			detail(w, 500, "invalid native legacy integer")
			return
		}
	}
	writeJSON(w, 200, legacyDamageResponse{result.Formula, json.Number(result.Minimum), json.Number(result.Maximum), json.Number(result.Random), result.MinimumPercent, result.MaximumPercent, result.RandomPercent})
}
