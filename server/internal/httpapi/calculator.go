package httpapi

import (
	"context"
	"database/sql"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"net/http"
	"os"
	"path/filepath"
	"pokemonbattleinference/server/internal/catalog"
	"pokemonbattleinference/server/internal/configurations"
	"pokemonbattleinference/server/internal/workerprocess"
	"strconv"
	"strings"
	"time"
)

// calculatorSideInput 是原静态计算器的一侧选择；指针区分必填缺失与合法零值。
type calculatorSideInput struct {
	PokemonID *int             `json:"pokemon_id"`
	Level     int              `json:"level"`
	Preset    *string          `json:"stat_preset"`
	Ability   *string          `json:"ability_identifier"`
	Item      *string          `json:"item_identifier"`
	Stages    calculatorStages `json:"stat_stages"`
}

// calculatorStages 保存七项 HTTP 整数等级；这里只检查边界，数值转换完全交给 Core stage。
type calculatorStages struct {
	Attack         int `json:"attack"`
	Defense        int `json:"defense"`
	SpecialAttack  int `json:"special_attack"`
	SpecialDefense int `json:"special_defense"`
	Speed          int `json:"speed"`
	Accuracy       int `json:"accuracy"`
	Evasion        int `json:"evasion"`
}

// UnmarshalJSON 在 data 进入应用前拒绝 null 与非整数；空对象保留全零默认。
func (stages *calculatorStages) UnmarshalJSON(data []byte) error {
	if string(data) == "null" {
		return errors.New("stat_stages must be an object")
	}
	type plain calculatorStages
	var result plain
	if err := json.Unmarshal(data, &result); err != nil {
		return err
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(data, &fields); err != nil {
		return err
	}
	for field, value := range fields {
		switch field {
		case "attack", "defense", "special_attack", "special_defense", "speed", "accuracy", "evasion":
			if string(value) == "null" {
				return errors.New("stat stages must be integers")
			}
		}
	}
	*stages = calculatorStages(result)
	return nil
}

// UnmarshalJSON 为 data 中省略的 level 应用原默认 50；显式 null 或缺必填由 Validate 拒绝。
func (side *calculatorSideInput) UnmarshalJSON(data []byte) error {
	type plain calculatorSideInput
	value := plain{Level: 50}
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
	*side = calculatorSideInput(value)
	return nil
}

// validate 对 side 的原 schema 范围进行检查；成功后所有必填指针可安全读取。
func (side calculatorSideInput) validate() error {
	if side.PokemonID == nil || side.Preset == nil || side.Ability == nil || len(*side.Ability) < 1 {
		return errors.New("pokemon_id, stat_preset and ability_identifier are required")
	}
	if side.Level < 1 || side.Level > 100 {
		return errors.New("level must be between 1 and 100")
	}
	for _, value := range []int{side.Stages.Attack, side.Stages.Defense, side.Stages.SpecialAttack, side.Stages.SpecialDefense, side.Stages.Speed, side.Stages.Accuracy, side.Stages.Evasion} {
		if value < -6 || value > 6 {
			return errors.New("stat stages must be between -6 and 6")
		}
	}
	return nil
}

// calculatorInput 保留原 endpoint 必填双方与招式；规则集由解析入口设置旧默认。
type calculatorInput struct {
	Ruleset  *string              `json:"ruleset_id"`
	Attacker *calculatorSideInput `json:"attacker"`
	Defender *calculatorSideInput `json:"defender"`
	MoveID   *int                 `json:"move_id"`
}

// calculatorProfile 仅保存用户模板的显式投入和展示信息；不计算派生能力值。
type calculatorProfile struct {
	EVs    configurations.Spread
	IVs    configurations.Spread
	Nature [6]int
	View   preset
}

// calculatorBattler 是静态 damage ABI 的完整可信输入；保持旧 can_evolve=false 的默认。
type calculatorBattler struct {
	Level   int                   `json:"level"`
	Types   []int                 `json:"types"`
	Stats   configurations.Spread `json:"stats"`
	Ability string                `json:"ability"`
	Item    string                `json:"item"`
}

// calculatorSideResult 使用原字段及显式 null，确保旧前端读取结果时无需迁移 DTO。
type calculatorSideResult struct {
	PokemonID        int                   `json:"pokemon_id"`
	Identifier       string                `json:"identifier"`
	DisplayName      string                `json:"display_name"`
	SpriteURL        string                `json:"sprite_url"`
	Level            int                   `json:"level"`
	PresetLabel      string                `json:"preset_label"`
	PresetAssumption string                `json:"preset_assumption"`
	Stats            configurations.Spread `json:"stats"`
	EffectiveAttack  *int                  `json:"effective_attack"`
	EffectiveHP      *int                  `json:"effective_hp"`
	EffectiveDefense *int                  `json:"effective_defense"`
}

// calculatorFraction 接收 Core 精确概率字符串；只在 HTTP 展示边界转换为原 float。
type calculatorFraction struct {
	Numerator   string `json:"numerator"`
	Denominator string `json:"denominator"`
}

// probability 将 fraction 转成旧展示值，非法 native 响应必须报错，不能返回伪零概率。
func (fraction calculatorFraction) probability() (float64, error) {
	value, ok := new(big.Rat).SetString(fraction.Numerator + "/" + fraction.Denominator)
	if !ok || value.Sign() < 0 || value.Cmp(big.NewRat(1, 1)) > 0 {
		return 0, errors.New("invalid native probability")
	}
	result, _ := value.Float64()
	return result, nil
}

// calculatorNativeDamage 接收完整 Core 伤害结果；trace 原样输出，不复制 modifier 计算或说明。
type calculatorNativeDamage struct {
	Kind             string             `json:"kind"`
	Rolls            []int              `json:"rolls"`
	HP               int                `json:"defender_hp"`
	Trace            json.RawMessage    `json:"trace"`
	OHKO             calculatorFraction `json:"ohko"`
	TwoHit           calculatorFraction `json:"two_hit"`
	GuaranteedOHKO   bool               `json:"guaranteed_ohko"`
	GuaranteedTwoHit bool               `json:"guaranteed_two_hit"`
}

// calculatorMoveResult 保留旧计算结果里的招式展示资料。
type calculatorMoveResult struct {
	ID         int    `json:"move_id"`
	Identifier string `json:"identifier"`
	Name       string `json:"display_name"`
	Type       string `json:"type"`
	TypeName   string `json:"type_name"`
	Category   string `json:"category"`
	Power      int    `json:"power"`
}

// calculatorDamageRange 只展示 native rolls 的区间、算术均值与百分比，不参与战斗求解。
type calculatorDamageRange struct {
	Min             int     `json:"min"`
	Max             int     `json:"max"`
	MinPercent      float64 `json:"min_percent"`
	MaxPercent      float64 `json:"max_percent"`
	Expected        float64 `json:"expected"`
	ExpectedPercent float64 `json:"expected_percent"`
	Rolls           []int   `json:"rolls"`
}

// calculatorKOResult 保留原概率浮点 DTO；精确求解仍由 Core 完成。
type calculatorKOResult struct {
	OHKO             float64 `json:"ohko_probability"`
	TwoHit           float64 `json:"two_hit_ko_probability"`
	GuaranteedOHKO   bool    `json:"guaranteed_ohko"`
	GuaranteedTwoHit bool    `json:"guaranteed_2hko"`
}

// calculatorScope 返回旧静态模式的机制范围；不能冒称完整回合支持。
type calculatorScope struct {
	Mode     string   `json:"mode"`
	Included []string `json:"included"`
	Excluded []string `json:"excluded"`
}

// calculatorResult 是原计算器的完整成功响应，没有异步任务或临时数据库对象。
type calculatorResult struct {
	Ruleset   string                `json:"ruleset_id"`
	Name      string                `json:"ruleset_name"`
	Attacker  calculatorSideResult  `json:"attacker"`
	Defender  calculatorSideResult  `json:"defender"`
	Move      calculatorMoveResult  `json:"move"`
	Damage    calculatorDamageRange `json:"damage"`
	KO        calculatorKOResult    `json:"ko"`
	Modifiers json.RawMessage       `json:"modifiers"`
	Scope     calculatorScope       `json:"scope"`
	Warnings  []string              `json:"warnings"`
}

// calculatorHandler 以同一知识快照编排三个独立 Core 批次；没有进程内公式或 Python fallback。
type calculatorHandler struct {
	store  *catalog.Store
	worker string
}

// registerCalculator 将原 POST /v1/calculator/damage 挂到真实 PG 与独立 Worker。
// mux 为主 router；db 由服务拥有，handler 不关闭连接池。
func registerCalculator(mux *http.ServeMux, db *sql.DB) {
	mux.Handle("POST /v1/calculator/damage", calculatorHandler{catalog.New(db), configuredWorker()})
}

// ServeHTTP 校验原请求、冻结 PG 资料、委托 Core 并输出兼容响应；ctx 的总预算为 30 秒。
// w 接收稳定错误/完整响应；r 的取消传递到 PG 和每个子进程，不返回半成品成功。
func (handler calculatorHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 30*time.Second)
	defer cancel()
	defaultRuleset := "pokemon-champion"
	input := calculatorInput{Ruleset: &defaultRuleset}
	if !decodeJSON(w, r, &input) {
		return
	}
	if input.Ruleset == nil || input.Attacker == nil || input.Defender == nil || input.MoveID == nil {
		detail(w, 422, "ruleset_id, attacker, defender and move_id are required")
		return
	}
	for _, side := range []*calculatorSideInput{input.Attacker, input.Defender} {
		if err := side.validate(); err != nil {
			detail(w, 422, err.Error())
			return
		}
	}
	snapshot, err := handler.store.Calculation(ctx, *input.Ruleset, *input.Attacker.PokemonID, *input.Defender.PokemonID, *input.MoveID)
	if err != nil {
		var invalid *catalog.CalculationInputError
		if errors.As(err, &invalid) {
			detail(w, 400, invalid.Error())
		} else if ctx.Err() != nil {
			calculatorFailure(w, ctx.Err())
		} else {
			detail(w, 503, "catalog storage unavailable")
		}
		return
	}
	result, err := handler.calculate(ctx, input, snapshot)
	if err != nil {
		calculatorFailure(w, err)
		return
	}
	writeJSON(w, 200, result)
}

// calculatorFailure 统一原输入错误、native 拒绝及生命周期故障；不公开路径/stderr/SQL。
func calculatorFailure(w http.ResponseWriter, err error) {
	var invalid *catalog.CalculationInputError
	var failure *workerprocess.Failure
	switch {
	case errors.As(err, &invalid):
		detail(w, 400, invalid.Error())
	case errors.Is(err, context.DeadlineExceeded):
		workerError(w, 504, "cancelled", "calculation request exceeded its deadline")
	case errors.Is(err, context.Canceled):
		workerError(w, 408, "cancelled", "calculation request was cancelled")
	case errors.Is(err, workerprocess.ErrOutputLimit):
		workerError(w, 413, "resource_limit", "worker response limit exceeded")
	case errors.As(err, &failure):
		status := 500
		if failure.Code == "unsupported" {
			status = 422
		} else if failure.Code == "invalid_input" {
			status = 400
		} else if failure.Code == "resource_limit" {
			status = 413
		} else if failure.Code == "cancelled" {
			status = 408
		}
		workerError(w, status, failure.Code, "isolated calculation worker rejected the request")
	case errors.Is(err, errCalculatorWorkerUnavailable):
		workerError(w, 503, "worker_unavailable", "isolated calculation worker is unavailable")
	default:
		workerError(w, 500, "invalid_worker_response", "isolated calculation worker returned an invalid response")
	}
}

// errCalculatorWorkerUnavailable 将无法启动和非法配置归类为稳定 503，不暴露文件系统路径。
var errCalculatorWorkerUnavailable = errors.New("isolated calculation worker is unavailable")

// batch 将 operations 发送到绝对路径单请求 Worker，返回与输入等长的独立 JSON 结果。
// ctx 是整个业务请求的共享截止；错误时不使用部分 results。
func (handler calculatorHandler) batch(ctx context.Context, operations []any) ([]json.RawMessage, error) {
	result, err := handler.batchEnvelope(ctx, operations)
	return result.Results, err
}

// businessCoreBatch 保留业务准备所需的完整原生版本和逐项结果，供冻结 admission 证据使用。
type businessCoreBatch struct {
	Version       int               `json:"schema_version"`
	EngineVersion string            `json:"engine_version"`
	RulesVersion  string            `json:"rules_version"`
	Results       []json.RawMessage `json:"results"`
}

// batchEnvelope 与 batch 共享唯一子进程传输边界；ctx 控制整个业务请求，无任何进程内计算 fallback。
// operations 为完整 ABI 值，返回版本和所有结果；失败时不发布部分成功。
func (handler calculatorHandler) batchEnvelope(ctx context.Context, operations []any) (businessCoreBatch, error) {
	var result businessCoreBatch
	if !filepath.IsAbs(handler.worker) {
		return result, errCalculatorWorkerUnavailable
	}
	info, err := os.Stat(handler.worker)
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0111 == 0 {
		return result, errCalculatorWorkerUnavailable
	}
	body, err := json.Marshal(struct {
		Version    int   `json:"schema_version"`
		Operations []any `json:"operations"`
	}{1, operations})
	if err != nil {
		return result, err
	}
	response, err := workerprocess.Execute(ctx, handler.worker, body)
	if err != nil {
		var failure *workerprocess.Failure
		if errors.As(err, &failure) || errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) || errors.Is(err, workerprocess.ErrOutputLimit) {
			return result, err
		}
		return result, errCalculatorWorkerUnavailable
	}
	if err = json.Unmarshal(response, &result); err != nil {
		return businessCoreBatch{}, err
	}
	if result.Version != 1 || len(result.Results) != len(operations) {
		return businessCoreBatch{}, errors.New("invalid native result count")
	}
	return result, nil
}

// scalarOperation 为旧单项性格模板保留 hp/stat ABI 的精确输入；不在 Go 计算任何能力公式。
type scalarOperation struct {
	Kind   string `json:"kind"`
	Base   int    `json:"base"`
	IV     int    `json:"iv"`
	EV     int    `json:"ev"`
	Level  int    `json:"level"`
	Nature int    `json:"nature_tenths,omitempty"`
}

// stageOperation 仅绑定 Core stage 的值和等级，返回值由 C++ 唯一实现决定。
type stageOperation struct {
	Kind  string `json:"kind"`
	Value int    `json:"value"`
	Stage int    `json:"stage"`
}

// scalarResults 校验 results 的 kind/value 后返回独立整数切片；kind 随各操作逐项核对。
func scalarResults(results []json.RawMessage, kinds []string) ([]int, error) {
	values := make([]int, len(results))
	for index, raw := range results {
		var result struct {
			Kind  string `json:"kind"`
			Value *int   `json:"value"`
		}
		if err := json.Unmarshal(raw, &result); err != nil {
			return nil, err
		}
		if result.Value == nil || result.Kind != kinds[index] || *result.Value < 1 {
			return nil, errors.New("invalid native scalar result")
		}
		values[index] = *result.Value
	}
	return values, nil
}

// spreadValues 按 Core 六轴固定顺序复制 spread，不修改传入对象。
func spreadValues(spread configurations.Spread) []int {
	return []int{spread.HP, spread.Attack, spread.Defense, spread.SpecialAttack, spread.SpecialDefense, spread.Speed}
}

// valuesSpread 把已校验六项 native 结果转回旧字段名；调用方保证 values 长度为六。
func valuesSpread(values []int) configurations.Spread {
	return configurations.Spread{HP: values[0], Attack: values[1], Defense: values[2], SpecialAttack: values[3], SpecialDefense: values[4], Speed: values[5]}
}

// calculate 按“能力值→等级→伤害”依赖顺序调用独立 Core；input/snapshot 都是本次自有值。
// 返回原 DTO，仅做展示取整和精确概率转换；任一阶段失败不会输出之前的部分结果。
func (handler calculatorHandler) calculate(ctx context.Context, input calculatorInput, snapshot catalog.CalculationSnapshot) (any, error) {
	sides := []*calculatorSideInput{input.Attacker, input.Defender}
	pokemon := []catalog.CalculationPokemon{snapshot.Attacker, snapshot.Defender}
	profiles := make([]calculatorProfile, 2)
	battlers := make([]calculatorBattler, 2)
	warnings := []string{}
	operations := []any{}
	kinds := []string{}
	for index, side := range sides {
		profile, err := readCalculatorProfile(*side.Preset)
		if err != nil {
			return nil, err
		}
		profiles[index] = profile
		ability, warning, err := calculatorAbility(pokemon[index], *side.Ability, index == 0)
		if err != nil {
			return nil, err
		}
		if warning != "" {
			warnings = append(warnings, warning)
		}
		item, err := calculatorItem(side.Item)
		if err != nil {
			return nil, err
		}
		battlers[index] = calculatorBattler{Level: side.Level, Types: pokemon[index].Types, Ability: ability, Item: item}
		base, ivs, evs := spreadValues(pokemon[index].Base), spreadValues(profile.IVs), spreadValues(profile.EVs)
		for stat := 0; stat < 6; stat++ {
			kind := "stat"
			nature := profile.Nature[stat]
			if stat == 0 {
				kind = "hp"
				nature = 0
			}
			operations = append(operations, scalarOperation{kind, base[stat], ivs[stat], evs[stat], side.Level, nature})
			kinds = append(kinds, kind)
		}
	}
	raw, err := handler.batch(ctx, operations)
	if err != nil {
		return nil, err
	}
	base, err := scalarResults(raw, kinds)
	if err != nil {
		return nil, err
	}
	operations = nil
	kinds = nil
	// 旧接口展示基础实际能力，伤害输入才应用等级；两者不能误用同一组字段。
	for index, side := range sides {
		stages := []int{side.Stages.Attack, side.Stages.Defense, side.Stages.SpecialAttack, side.Stages.SpecialDefense, side.Stages.Speed}
		for stat, stage := range stages {
			operations = append(operations, stageOperation{"stage", base[index*6+stat+1], stage})
			kinds = append(kinds, "stage")
		}
	}
	raw, err = handler.batch(ctx, operations)
	if err != nil {
		return nil, err
	}
	staged, err := scalarResults(raw, kinds)
	if err != nil {
		return nil, err
	}
	for index := range battlers {
		values := []int{base[index*6]}
		values = append(values, staged[index*5:index*5+5]...)
		battlers[index].Stats = valuesSpread(values)
	}
	damageOperation := struct {
		Kind         string            `json:"kind"`
		Generation   int               `json:"generation_id"`
		VersionGroup int               `json:"version_group_id"`
		Attacker     calculatorBattler `json:"attacker"`
		Defender     calculatorBattler `json:"defender"`
		Move         struct {
			Type     int    `json:"type"`
			Category string `json:"category"`
			Power    int    `json:"power"`
		} `json:"move"`
		Chart []catalog.TypeFactor `json:"type_chart"`
	}{Kind: "damage", Generation: snapshot.Rules.Generation, VersionGroup: snapshot.Rules.VersionGroup, Attacker: battlers[0], Defender: battlers[1], Chart: snapshot.Chart}
	damageOperation.Move.Type = snapshot.Move.Type
	damageOperation.Move.Category = snapshot.Move.Category
	damageOperation.Move.Power = snapshot.Move.Power
	raw, err = handler.batch(ctx, []any{damageOperation})
	if err != nil {
		return nil, err
	}
	var damage calculatorNativeDamage
	if err = json.Unmarshal(raw[0], &damage); err != nil {
		return nil, err
	}
	if damage.Kind != "damage" || len(damage.Rolls) != 16 || damage.HP != base[6] || !json.Valid(damage.Trace) {
		return nil, errors.New("invalid native damage result")
	}
	for _, side := range sides {
		if side.Stages.Speed != 0 || side.Stages.Accuracy != 0 || side.Stages.Evasion != 0 {
			warnings = append(warnings, "当前单次伤害按招式已命中计算；速度、命中和回避等级已保留，但不改变本次伤害值。")
			break
		}
	}
	return calculatorResponse(input, snapshot, profiles, base, staged, damage, warnings)
}

// calculatorAbility 校验 identifier 确属 pokemon 的当前历史特性；只为旧契约允许的未实现特性加明确 warning。
// attacker 决定旧本地化角色文案；返回 Core identifier、可选 warning 或原输入错误。
func calculatorAbility(pokemon catalog.CalculationPokemon, identifier string, attacker bool) (string, string, error) {
	role, label := "defender", "防守方"
	if attacker {
		role, label = "attacker", "攻击方"
	}
	normalized := strings.TrimSpace(identifier)
	if normalized == "" {
		return "", "", &catalog.CalculationInputError{Message: role + " ability_identifier is required"}
	}
	for _, option := range pokemon.Abilities {
		if option.Identifier == normalized {
			if !option.Implemented {
				return "none", fmt.Sprintf("%s特性“%s”尚未实现，本次按无特性处理。", label, option.DisplayName), nil
			}
			return strings.ReplaceAll(normalized, "-", "_"), "", nil
		}
	}
	return "", "", &catalog.CalculationInputError{Message: fmt.Sprintf("ability is not available for %s in this ruleset: %s", role, normalized)}
}

// calculatorItem 复现旧 HTTP 可接受的英文和十项中文 alias，只翻译选择，不复制道具效果。
// identifier 为空/空白/精确 none 表示无道具；未知项返回原输入错误。
func calculatorItem(identifier *string) (string, error) {
	if identifier == nil || strings.TrimSpace(*identifier) == "" || *identifier == "none" {
		return "none", nil
	}
	value := strings.ReplaceAll(strings.ReplaceAll(strings.ToLower(strings.TrimSpace(*identifier)), "-", "_"), " ", "_")
	aliases := map[string]string{"生命宝珠": "life_orb", "生命寶珠": "life_orb", "讲究头带": "choice_band", "講究頭帶": "choice_band", "讲究眼镜": "choice_specs", "講究眼鏡": "choice_specs", "达人带": "expert_belt", "達人帶": "expert_belt", "进化奇石": "eviolite", "進化奇石": "eviolite"}
	if alias, exists := aliases[value]; exists {
		value = alias
	}
	switch value {
	case "life_orb", "choice_band", "choice_specs", "expert_belt", "eviolite":
		return value, nil
	}
	return "", &catalog.CalculationInputError{Message: "unsupported item_identifier: " + *identifier}
}

// readCalculatorProfile 解释原 key 或完整不可变快照；单轴 plus 不降低其他轴，区别于 paired nature。
// value 是原 stat_preset；返回仅包含显式输入和文案的 profile，无派生计算。
func readCalculatorProfile(value string) (calculatorProfile, error) {
	profile := calculatorProfile{IVs: configurations.Spread{HP: 31, Attack: 31, Defense: 31, SpecialAttack: 31, SpecialDefense: 31, Speed: 31}, Nature: [6]int{10, 10, 10, 10, 10, 10}}
	if strings.HasPrefix(value, "preset-snapshot:") {
		body, err := base64.RawURLEncoding.DecodeString(strings.TrimRight(strings.TrimPrefix(value, "preset-snapshot:"), "="))
		var snapshot struct {
			Nature string                 `json:"nature_id"`
			EVs    *configurations.Spread `json:"evs"`
			IVs    *configurations.Spread `json:"ivs"`
			Label  *string                `json:"label"`
		}
		if err != nil || json.Unmarshal(body, &snapshot) != nil || snapshot.EVs == nil || snapshot.IVs == nil {
			return profile, &catalog.CalculationInputError{Message: "invalid stat configuration snapshot"}
		}
		command := configurations.Command{Name: "snapshot", NatureID: snapshot.Nature, EVs: snapshot.EVs, IVs: snapshot.IVs, Role: "both", BindingKind: "global"}
		if err = command.Validate(); err != nil {
			return profile, &catalog.CalculationInputError{Message: err.Error()}
		}
		profile.EVs, profile.IVs = *snapshot.EVs, *snapshot.IVs
		axes := map[string]int{"attack": 1, "defense": 2, "special_attack": 3, "special_defense": 4, "speed": 5}
		for _, nature := range configurations.Natures() {
			if nature.Identifier == snapshot.Nature && nature.IncreasedStat != nil {
				profile.Nature[axes[*nature.IncreasedStat]] = 11
				profile.Nature[axes[*nature.DecreasedStat]] = 9
			}
		}
		label := "自定义配置"
		if snapshot.Label != nil {
			label = strings.TrimSpace(*snapshot.Label)
		}
		if label == "" {
			label = "配置预设"
		}
		profile.View = preset{value, label, "来自配置预设快照，包含显式 nature / EV / IV。"}
		return profile, nil
	}
	for _, options := range legacyPresets {
		for _, option := range options {
			if option.Key == value {
				profile.View = option
			}
		}
	}
	if profile.View.Key == "" {
		return profile, &catalog.CalculationInputError{Message: "unsupported stat preset: " + value}
	}
	switch value {
	case "max_atk_neutral", "max_atk_plus":
		profile.EVs.Attack = 252
	case "max_spatk_neutral", "max_spatk_plus":
		profile.EVs.SpecialAttack = 252
	case "max_hp":
		profile.EVs.HP = 252
	case "max_hp_def", "max_hp_def_plus":
		profile.EVs.HP = 252
		profile.EVs.Defense = 252
	case "max_hp_spdef", "max_hp_spdef_plus":
		profile.EVs.HP = 252
		profile.EVs.SpecialDefense = 252
	}
	switch value {
	case "max_atk_plus":
		profile.Nature[1] = 11
	case "max_spatk_plus":
		profile.Nature[3] = 11
	case "max_hp_def_plus":
		profile.Nature[2] = 11
	case "max_hp_spdef_plus":
		profile.Nature[4] = 11
	}
	return profile, nil
}

// roundedDisplay 沿旧 Python round(x,1) 的二进制浮点十进制舍入，不改变 Core 整数伤害。
func roundedDisplay(value float64) float64 {
	result, _ := strconv.ParseFloat(strconv.FormatFloat(value, 'f', 1, 64), 64)
	return result
}

// calculatorResponse 将原生伤害、概率和 trace 映射成旧 DTO；其余参数是本次已校验快照。
// base/staged 分别为两侧基础12轴/等级后10轴，profiles 两项；只做展示均值/百分比与文案。
func calculatorResponse(input calculatorInput, snapshot catalog.CalculationSnapshot, profiles []calculatorProfile, base, staged []int, damage calculatorNativeDamage, warnings []string) (any, error) {
	ohko, err := damage.OHKO.probability()
	if err != nil {
		return nil, err
	}
	two, err := damage.TwoHit.probability()
	if err != nil {
		return nil, err
	}
	pokemon := []catalog.CalculationPokemon{snapshot.Attacker, snapshot.Defender}
	sides := []*calculatorSideInput{input.Attacker, input.Defender}
	resultSides := make([]calculatorSideResult, 2)
	for index, side := range sides {
		resultSides[index] = calculatorSideResult{PokemonID: pokemon[index].ID, Identifier: pokemon[index].Identifier, DisplayName: pokemon[index].Name, SpriteURL: fmt.Sprintf("/api/v1/assets/pokemon/%d/sprite?ruleset_id=%s&slot=front_default", pokemon[index].ID, snapshot.Rules.ID), Level: side.Level, PresetLabel: profiles[index].View.Label, PresetAssumption: profiles[index].View.Assumption, Stats: valuesSpread(base[index*6 : index*6+6])}
	}
	attack, defense := staged[0], staged[6]
	if snapshot.Move.Category == "special" {
		attack, defense = staged[2], staged[8]
	}
	hp := base[6]
	resultSides[0].EffectiveAttack = &attack
	resultSides[1].EffectiveHP = &hp
	resultSides[1].EffectiveDefense = &defense
	minimum, maximum, total := damage.Rolls[0], damage.Rolls[0], 0
	for _, value := range damage.Rolls {
		if value < 0 {
			return nil, errors.New("invalid native damage roll")
		}
		if value < minimum {
			minimum = value
		}
		if value > maximum {
			maximum = value
		}
		total += value
	}
	expected := float64(total) / float64(len(damage.Rolls))
	return calculatorResult{
		Ruleset: snapshot.Rules.ID, Name: snapshot.Rules.Name, Attacker: resultSides[0], Defender: resultSides[1],
		Move:   calculatorMoveResult{snapshot.Move.ID, snapshot.Move.Identifier, snapshot.Move.Name, snapshot.Move.TypeIdentifier, snapshot.Move.TypeName, snapshot.Move.Category, snapshot.Move.Power},
		Damage: calculatorDamageRange{minimum, maximum, roundedDisplay(float64(minimum) / float64(hp) * 100), roundedDisplay(float64(maximum) / float64(hp) * 100), roundedDisplay(expected), roundedDisplay(expected / float64(hp) * 100), damage.Rolls},
		KO:     calculatorKOResult{ohko, two, damage.GuaranteedOHKO, damage.GuaranteedTwoHit}, Modifiers: damage.Trace, Warnings: warnings,
		Scope: calculatorScope{Mode: "basic", Included: []string{"等级", "能力值模板", "攻击/防御/特攻/特防能力等级", "已实现持有道具", "已实现特性", "招式固定威力", "STAB", "属性克制", "16 档随机伤害"}, Excluded: []string{"速度/命中/回避对单次伤害值的影响", "未实现特性", "未实现道具", "天气", "场地", "状态", "会心", "双打范围修正", "动态威力招式"}},
	}, nil
}
