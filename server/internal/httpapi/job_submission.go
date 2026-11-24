package httpapi

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"pokemonbattleinference/server/internal/catalog"
	"pokemonbattleinference/server/internal/configurations"
	"pokemonbattleinference/server/internal/jobs"
	"pokemonbattleinference/server/internal/workerprocess"
	"sort"
	"strconv"
	"strings"
	"time"
	"unicode/utf16"
	"unicode/utf8"
)

// jobSubmissionHandler 只做原 HTTP/知识/持久化编排；全部 strict、能力计算、组合和 canonical 由独立 Core 执行。
type jobSubmissionHandler struct {
	catalog *catalog.Store
	store   *jobs.Store
	core    calculatorHandler
}

// registerJobSubmission 挂接原 HTTP202 创建合同；不存在任意 Core JSON 直接入队入口。
func registerJobSubmission(mux *http.ServeMux, db *sql.DB) {
	mux.Handle("POST /v1/inference/configuration-jobs", jobSubmissionHandler{catalog.New(db), jobs.New(db), calculatorHandler{worker: configuredWorker()}})
}

// jobInvalid 返回原业务 ValueError envelope；message 是安全的输入说明，不能包含驱动/连接资料。
func jobInvalid(w http.ResponseWriter, message string) {
	writeJSON(w, 422, map[string]any{"detail": map[string]string{"code": "battle_inference_job_invalid_request", "message": message}})
}

// ServeHTTP 用单个有界ctx完成严格准入/分页规划/共享冻结/原子入库；客户端取消不会保留半个任务。
func (handler jobSubmissionHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 30*time.Second)
	defer cancel()
	request := jobSubmissionRequest{Execution: defaultJobBudget()}
	decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 8<<20))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&request); err != nil {
		detail(w, 422, "invalid job request body")
		return
	}
	var extra any
	if decoder.Decode(&extra) != io.EOF {
		detail(w, 422, "request must contain one JSON value")
		return
	}
	if err := request.validate(); err != nil {
		jobInvalid(w, err.Error())
		return
	}
	key, hasKey := r.Header["Idempotency-Key"]
	idempotency := ""
	if hasKey {
		if len(key) > 0 {
			idempotency = key[0]
		}
		if idempotency == "" || idempotency != strings.TrimSpace(idempotency) || utf8.RuneCountInString(idempotency) > 200 {
			jobInvalid(w, "idempotency_key must be normalized and at most 200 characters")
			return
		}
	}
	// 原应用在进入validator前规范化ID顺序；这里只用于传输/幂等输入，case组合及身份仍由Core生成。
	sort.Ints(request.Attacker.Moves)
	sort.Ints(request.Defender.Moves)
	// 本入口与原 HTTP 一样固定使用 PokemonChampion composition；先拒绝与工厂不相同的规则轴。
	if request.Ruleset != "pokemon-champion" {
		jobInvalid(w, "effect factory ruleset does not match candidate command")
		return
	}
	snapshot, err := handler.catalog.Inference(ctx, request.Ruleset, request.Version, []int{request.Attacker.Fixed.PokemonID, request.Defender.Fixed.PokemonID})
	if err != nil {
		var input *catalog.CalculationInputError
		if errors.As(err, &input) {
			jobInvalid(w, input.Error())
		} else if ctx.Err() != nil {
			calculatorFailure(w, ctx.Err())
		} else {
			detail(w, 503, "catalog storage unavailable")
		}
		return
	}
	definition, failures, err := handler.prepare(ctx, request, snapshot, idempotency)
	if err != nil {
		if ctx.Err() != nil {
			calculatorFailure(w, ctx.Err())
		} else {
			submissionFailure(w, err)
		}
		return
	}
	if len(failures) > 0 {
		rejectJobAdmission(w, failures)
		return
	}
	now := time.Now().UTC().Truncate(time.Microsecond)
	if _, err = handler.store.Create(ctx, definition, now); err != nil {
		if ctx.Err() != nil {
			calculatorFailure(w, ctx.Err())
			return
		}
		if errors.Is(err, jobs.ErrConflict) {
			writeJSON(w, 409, map[string]any{"detail": map[string]string{"code": "battle_inference_job_conflict", "message": "job id already has a different immutable definition"}})
			return
		}
		detail(w, 503, "job storage unavailable")
		return
	}
	job, err := handler.store.Get(ctx, definition.ID)
	if err != nil {
		detail(w, 503, "job storage unavailable")
		return
	}
	writeJSON(w, 202, struct {
		ID      string `json:"job_id"`
		Status  string `json:"status"`
		Count   int    `json:"submitted_configuration_pairs"`
		Created string `json:"created_at"`
	}{job.ID, "pending", len(definition.Cases), pythonTimestamp(job.CreatedAt)})
}

// submissionFailure 将 Core/配置输入错误转换为明确失败；不把部分规划页当作成功提交。
func submissionFailure(w http.ResponseWriter, err error) {
	var input *catalog.CalculationInputError
	var failure *workerprocess.Failure
	if errors.As(err, &input) {
		jobInvalid(w, input.Error())
		return
	}
	if errors.As(err, &failure) && failure.Code == "invalid_input" {
		jobInvalid(w, "Core rejected the job command or its frozen facts")
		return
	}
	calculatorFailure(w, err)
}

// rejectJobAdmission 保留原全部去重失败及稳定摘要，不删除不可选择候选后继续规划。
func rejectJobAdmission(w http.ResponseWriter, failures []jobAdmissionFailure) {
	parts := make([]string, 0, len(failures))
	for _, failure := range failures {
		parts = append(parts, failure.Source+":"+failure.Requested+":"+failure.Status+":missing="+strings.Join(failure.Missing, ","))
	}
	writeJSON(w, 422, map[string]any{"detail": struct {
		Code     string                `json:"code"`
		Message  string                `json:"message"`
		Failures []jobAdmissionFailure `json:"failures"`
	}{"strict_mechanism_admission_rejected", "strict mechanism admission rejected: " + strings.Join(parts, "; "), failures}})
}

// selectedJobFact 记录请求与唯一Core结果的索引；不合法PG选择保留缺失失败，不伪造机制快照。
type selectedJobFact struct {
	index     int
	requested string
	missing   *jobAdmissionFailure
}

// jobSideFacts 保持原validator分块顺序所需的三类选择，实际机制状态只来自Core。
type jobSideFacts struct {
	moves   []selectedJobFact
	ability selectedJobFact
	item    selectedJobFact
	pool    []jobs.FrozenMove
}

// nativeJobMove 把 move 的原 version-aware 字段映射成 MoveSpec；变化威力攻击返回nil以保留不可执行事实。
func nativeJobMove(move catalog.InferenceMove) *jobMoveSpec {
	if move.Power == nil && move.Category != "status" {
		return nil
	}
	result := &jobMoveSpec{MoveID: move.ID, Name: move.Name, MaxPP: move.PP, Priority: move.Priority, Accuracy: move.Accuracy, Effect: move.Effect}
	result.Move.Type = move.Type.ID
	result.Move.Category = move.Category
	if move.Power != nil {
		result.Move.Power = *move.Power
	}
	return result
}

// appendJobFacts 根据同一snapshot里的合法候选建立side的完整原始事实；未知选择输出原missing失败。
// facts 是本次独占累积切片；sideIndex仅决定关联侧，不参与任何求解或权重。
func appendJobFacts(facts *[]jobAdmissionFact, selection jobSelection, pokemon catalog.InferencePokemon, items []catalog.InferenceItem, version, sideIndex int) (jobSideFacts, error) {
	result := jobSideFacts{moves: make([]selectedJobFact, 0, len(selection.Moves)), pool: []jobs.FrozenMove{}}
	side := "attacker"
	if sideIndex == 1 {
		side = "defender"
	}
	for _, id := range selection.Moves {
		selected := selectedJobFact{index: -1, requested: strconv.Itoa(id)}
		found := false
		for _, move := range pokemon.Moves {
			if move.ID != id {
				continue
			}
			found = true
			spec := nativeJobMove(move)
			moveID := id
			fact := jobAdmissionFact{Side: side, MoveID: &moveID, Move: spec, jobAdmissionCandidate: jobAdmissionCandidate{Source: "move", Effect: move.Effect, Mechanism: move.Capability.Identifier, RepositoryReason: move.Capability.Reason, BaseExecutable: move.Category == "status" || move.Power != nil, AllowNoEffect: move.Category != "status" && move.Effect == nil}}
			selected.index = len(*facts)
			*facts = append(*facts, fact)
			if spec != nil {
				encoded, err := json.Marshal(spec)
				if err != nil {
					return result, err
				}
				slot, err := json.Marshal(struct {
					ID      int `json:"move_id"`
					Current int `json:"current_pp"`
					Maximum int `json:"max_pp"`
				}{id, move.PP, move.PP})
				if err != nil {
					return result, err
				}
				result.pool = append(result.pool, jobs.FrozenMove{MoveID: id, Spec: encoded, Slot: slot})
			}
			break
		}
		if !found {
			selected.missing = &jobAdmissionFailure{"move", strconv.Itoa(id), "unsupported", fmt.Sprintf("move %d is not legal for Pokemon %d in version group %d", id, pokemon.ID, version), []string{fmt.Sprintf("move-id-%d", id)}}
		}
		result.moves = append(result.moves, selected)
	}
	result.ability = selectedJobFact{index: -1, requested: selection.Fixed.Ability}
	for _, ability := range pokemon.Abilities {
		if ability.Identifier != selection.Fixed.Ability {
			continue
		}
		effect := ability.Effect
		result.ability.index = len(*facts)
		*facts = append(*facts, jobAdmissionFact{Side: side, jobAdmissionCandidate: jobAdmissionCandidate{Source: "ability", Effect: &effect, Mechanism: ability.Capability.Identifier, RepositoryReason: ability.Capability.Reason, BaseExecutable: true}})
		break
	}
	if result.ability.index < 0 {
		result.ability.missing = &jobAdmissionFailure{"ability", selection.Fixed.Ability, "unsupported", fmt.Sprintf("ability %s is not legal for Pokemon %d in version group %d", pythonRepr(selection.Fixed.Ability), pokemon.ID, version), []string{selection.Fixed.Ability}}
	}
	itemID := "none"
	if selection.Fixed.Item != nil {
		itemID = *selection.Fixed.Item
	}
	result.item = selectedJobFact{index: -1, requested: itemID}
	for _, item := range items {
		if item.Identifier != itemID {
			continue
		}
		result.item.index = len(*facts)
		*facts = append(*facts, jobAdmissionFact{Side: side, jobAdmissionCandidate: jobAdmissionCandidate{Source: "item", Effect: item.Effect, Mechanism: item.Capability.Identifier, RepositoryReason: item.Capability.Reason, BaseExecutable: true, AllowNoEffect: item.Effect == nil}})
		break
	}
	if result.item.index < 0 {
		result.item.missing = &jobAdmissionFailure{"item", itemID, "unsupported", fmt.Sprintf("item %s is not available in the controlled boundary for version group %d", pythonRepr(itemID), version), []string{itemID}}
	}
	return result, nil
}

// admissionFailures 按原每四招一块的validator顺序合并全部失败，并复现跨块/跨侧稳定去重。
// sides 与decisions均来自本次冻结资料/Core，不在Go推断任何支持状态或缺失机制。
func admissionFailures(sides []jobSideFacts, decisions []jobAdmissionDecision) []jobAdmissionFailure {
	result := []jobAdmissionFailure{}
	seen := map[string]bool{}
	appendFailure := func(selected selectedJobFact) {
		// 仅格式化Core拒绝或PG合法性缺失，不把不可选择状态改成可执行。
		failure := selected.missing
		if failure == nil {
			decision := decisions[selected.index]
			if decision.Selectable {
				return
			}
			failure = &jobAdmissionFailure{decision.Source, selected.requested, decision.Status, decision.Reason, decision.Missing}
		}
		encoded, _ := json.Marshal(failure)
		key := string(encoded)
		if !seen[key] {
			seen[key] = true
			result = append(result, *failure)
		}
	}
	for _, side := range sides {
		for start := 0; start < len(side.moves); start += 4 {
			end := start + 4
			if end > len(side.moves) {
				end = len(side.moves)
			}
			for _, selected := range side.moves[start:end] {
				appendFailure(selected)
			}
			appendFailure(side.ability)
			appendFailure(side.item)
		}
	}
	return result
}

// prepare 用相同事实先完整coverage、再让Core重复strict并分页产生全部canonical case，最后冻结共享模板。
func (handler jobSubmissionHandler) prepare(ctx context.Context, request jobSubmissionRequest, snapshot catalog.InferenceSnapshot, key string) (jobs.Definition, []jobAdmissionFailure, error) {
	command := request.jobPoolCommand
	facts := jobAdmissionSnapshot{Ruleset: command.Ruleset, Version: command.Version, Revision: command.Revision, Candidates: []jobAdmissionFact{}}
	sides := make([]jobSideFacts, 2)
	for index, selection := range []jobSelection{command.Attacker, command.Defender} {
		var err error
		sides[index], err = appendJobFacts(&facts.Candidates, selection, snapshot.Pokemon[index], snapshot.Items, command.Version, index)
		if err != nil {
			return jobs.Definition{}, nil, err
		}
	}
	candidates := make([]jobAdmissionCandidate, 0, len(facts.Candidates))
	for _, fact := range facts.Candidates {
		candidates = append(candidates, fact.jobAdmissionCandidate)
	}
	coverageInput := struct {
		Mode       string                  `json:"mode"`
		Factory    string                  `json:"factory"`
		Repository string                  `json:"repository_mode"`
		Candidates []jobAdmissionCandidate `json:"candidates"`
	}{"admission", "transparent_inference", "factory_reconciled", candidates}
	coverage, err := handler.core.batchEnvelope(ctx, []any{struct {
		Kind  string `json:"kind"`
		Input any    `json:"input"`
	}{"configuration_coverage", coverageInput}})
	if err != nil {
		return jobs.Definition{}, nil, err
	}
	var checked struct {
		Kind       string                 `json:"kind"`
		Mode       string                 `json:"mode"`
		Candidates []jobAdmissionDecision `json:"candidates"`
	}
	if err = json.Unmarshal(coverage.Results[0], &checked); err != nil {
		return jobs.Definition{}, nil, err
	}
	if checked.Kind != "configuration_coverage" || checked.Mode != "admission" || len(checked.Candidates) != len(candidates) {
		return jobs.Definition{}, nil, errors.New("invalid native admission result")
	}
	if failures := admissionFailures(sides, checked.Candidates); len(failures) > 0 {
		return jobs.Definition{}, failures, nil
	}
	id, err := submissionJobID(request, key)
	if err != nil {
		return jobs.Definition{}, nil, err
	}
	definition := jobs.Definition{ID: id, RulesetID: command.Ruleset, VersionGroupID: command.Version, Revision: command.Revision, Spec: request.spec(), Cases: []jobs.CaseDefinition{}}
	definition.Admission, err = json.Marshal(struct {
		Facts  jobAdmissionSnapshot `json:"facts"`
		Result businessCoreBatch    `json:"core_response"`
	}{facts, coverage})
	if err != nil {
		return jobs.Definition{}, nil, err
	}
	// Core只返回有界规划页；这里仅拼接已生成的case，不做组合或按页面重新计算分母。
	offset, total := 0, -1
	for {
		input := struct {
			Command   jobPoolCommand       `json:"command"`
			Admission jobAdmissionSnapshot `json:"admission"`
			Offset    int                  `json:"offset"`
			Limit     int                  `json:"limit"`
		}{command, facts, offset, 500}
		raw, err := handler.core.batch(ctx, []any{struct {
			Kind  string `json:"kind"`
			Input any    `json:"input"`
		}{"job_move_pool", input}})
		if err != nil {
			return jobs.Definition{}, nil, err
		}
		var page jobPoolPage
		if err = json.Unmarshal(raw[0], &page); err != nil {
			return jobs.Definition{}, nil, err
		}
		if page.Kind != "job_move_pool" || page.Offset != offset || page.CaseCount < 1 || page.Next != offset+len(page.Cases) || page.Next > page.CaseCount || (total >= 0 && total != page.CaseCount) || (page.HasMore && len(page.Cases) == 0) {
			return jobs.Definition{}, nil, errors.New("invalid native job page")
		}
		total = page.CaseCount
		for _, item := range page.Cases {
			if item.Ordinal != len(definition.Cases) {
				return jobs.Definition{}, nil, errors.New("native case ordering changed")
			}
			definition.Cases = append(definition.Cases, jobs.CaseDefinition{PairID: item.PairID, AttackerID: item.AttackerID, DefenderID: item.DefenderID, AttackerMoves: item.AttackerMoves, DefenderMoves: item.DefenderMoves})
		}
		if !page.HasMore {
			if len(definition.Cases) != total {
				return jobs.Definition{}, nil, errors.New("native job page is incomplete")
			}
			break
		}
		offset = page.Next
	}
	// 原 strict 不校验 stat profile；未知模板保留原202，在worker领取各case后才落准备失败。
	profiles, preparation := jobProfiles([]jobSelection{request.Attacker, request.Defender})
	if preparation != nil {
		definition.PreparationFailure = preparation
		return definition, nil, definition.Validate()
	}
	definition.CoreTemplate, err = handler.template(ctx, request, snapshot, sides, profiles)
	if err != nil {
		return jobs.Definition{}, nil, err
	}
	return definition, nil, definition.Validate()
}

// submissionJobID 沿原应用的随机UUID/幂等SHA边界生成任务ID；不生成任何case canonical身份。
func submissionJobID(request jobSubmissionRequest, key string) (string, error) {
	if key == "" {
		var identity [16]byte
		if _, err := rand.Read(identity[:]); err != nil {
			return "", err
		}
		identity[6] = (identity[6] & 15) | 64
		identity[8] = (identity[8] & 63) | 128
		return "battle-inference-" + hex.EncodeToString(identity[:]), nil
	}
	fixed := func(value jobFixed) []any {
		return []any{value.PokemonID, value.FormID, value.Level, value.Profile, value.Ability, value.Item}
	}
	command, budget := request.jobPoolCommand, request.Execution
	value := []any{key, command.Contract, command.Ruleset, command.Version, command.Revision, fixed(command.Attacker.Fixed), command.Attacker.Moves, fixed(command.Defender.Fixed), command.Defender.Moves, command.Weight, command.AttackerPolicy, command.DefenderPolicy, command.Mechanism, budget.ProcessCount, budget.QueueDepth, budget.MaxNodes, budget.MaxEdges, budget.MaxTurns}
	var body strings.Builder
	encoder := json.NewEncoder(&body)
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode(value); err != nil {
		return "", err
	}
	var ascii strings.Builder
	for _, character := range strings.TrimSuffix(body.String(), "\n") {
		if character < 128 {
			ascii.WriteRune(character)
		} else if character <= 65535 {
			fmt.Fprintf(&ascii, `\u%04x`, character)
		} else {
			first, second := utf16.EncodeRune(character)
			fmt.Fprintf(&ascii, `\u%04x\u%04x`, first, second)
		}
	}
	digest := sha256.Sum256([]byte(ascii.String()))
	return "battle-inference-idempotent-" + hex.EncodeToString(digest[:]), nil
}

// template 由Core配置能力实际计算结果构造一次共享初始状态；不计算任何伤害/能力/权重公式。
// profiles 是同一请求按原 inference 七项模板/snapshot 解析后的两侧值；ctx 取消终止原生子进程。
func (handler jobSubmissionHandler) template(ctx context.Context, request jobSubmissionRequest, snapshot catalog.InferenceSnapshot, sides []jobSideFacts, profiles []calculatorProfile) (*jobs.FixedBattleTemplate, error) {
	operations := []any{}
	selections := []jobSelection{request.Attacker, request.Defender}
	for index, selection := range selections {
		profile := profiles[index]
		nature := make([]float64, 5)
		for axis := range nature {
			nature[axis] = float64(profile.Nature[axis+1]) / 10
		}
		preset := struct {
			Profile struct {
				IVs    configurations.Spread `json:"ivs"`
				EVs    configurations.Spread `json:"evs"`
				Nature []float64             `json:"nature"`
			} `json:"profile"`
			Label string `json:"label"`
		}{Label: profile.View.Label}
		preset.Profile.IVs = profile.IVs
		preset.Profile.EVs = profile.EVs
		preset.Profile.Nature = nature
		input := struct {
			Base        configurations.Spread `json:"base"`
			Level       int                   `json:"level"`
			Enumeration struct {
				Mode    string `json:"mode"`
				Presets []any  `json:"presets"`
			} `json:"enumeration"`
			Maximum int `json:"max_raw_profiles"`
		}{Base: snapshot.Pokemon[index].Base, Level: selection.Fixed.Level, Maximum: 1}
		input.Enumeration.Mode = "preset"
		input.Enumeration.Presets = []any{preset}
		operations = append(operations, struct {
			Kind  string `json:"kind"`
			Input any    `json:"input"`
		}{"configuration_stats", input})
	}
	computed, err := handler.core.batch(ctx, operations)
	if err != nil {
		return nil, err
	}
	battlers := make([]any, 2)
	for index, selection := range selections {
		var result struct {
			Kind    string `json:"kind"`
			Classes []struct {
				Actual configurations.Spread `json:"actual"`
			} `json:"classes"`
			Count string `json:"raw_profile_count"`
		}
		if json.Unmarshal(computed[index], &result) != nil || result.Kind != "configuration_stats" || len(result.Classes) != 1 || result.Count != "1" || len(sides[index].pool) == 0 {
			return nil, errors.New("invalid native fixed stat profile")
		}
		pokemon := snapshot.Pokemon[index]
		types := make([]int, 0, len(pokemon.Types))
		for _, entry := range pokemon.Types {
			types = append(types, entry.ID)
		}
		item := "none"
		if selection.Fixed.Item != nil && *selection.Fixed.Item != "none" {
			item = strings.ReplaceAll(*selection.Fixed.Item, "-", "_")
		}
		value := struct {
			Level     int                   `json:"level"`
			Types     []int                 `json:"types"`
			Stats     configurations.Spread `json:"stats"`
			Ability   string                `json:"ability"`
			Item      string                `json:"item"`
			CanEvolve bool                  `json:"can_evolve"`
		}{selection.Fixed.Level, types, result.Classes[0].Actual, strings.ReplaceAll(selection.Fixed.Ability, "-", "_"), item, pokemon.CanEvolve}
		spec := struct {
			ID      int               `json:"pokemon_id"`
			Name    string            `json:"name"`
			Pokemon any               `json:"pokemon"`
			Moves   []json.RawMessage `json:"moves"`
		}{pokemon.ID, pokemon.Identifier, value, []json.RawMessage{sides[index].pool[0].Spec}}
		battlers[index] = struct {
			Spec  any               `json:"spec"`
			HP    int               `json:"current_hp"`
			Slots []json.RawMessage `json:"move_slots"`
		}{spec, result.Classes[0].Actual.HP, []json.RawMessage{sides[index].pool[0].Slot}}
	}
	operation := map[string]any{"kind": "fixed_battle", "state": map[string]any{"attacker": battlers[0], "defender": battlers[1], "rules": map[string]any{"ruleset_id": request.Ruleset, "version_group_id": request.Version, "level": request.Attacker.Fixed.Level, "max_turns": request.Execution.MaxTurns}}, "type_chart": snapshot.Chart, "attacker_policy": request.AttackerPolicy, "defender_policy": request.DefenderPolicy, "observer": "attacker", "graph_limits": map[string]any{"max_nodes": request.Execution.MaxNodes, "max_edges": request.Execution.MaxEdges, "max_turns": request.Execution.MaxTurns}, "max_equation_nodes": nil, "include_graph": false, "progress_interval": 100}
	encoded, err := json.Marshal(struct {
		Version    int   `json:"schema_version"`
		Operations []any `json:"operations"`
	}{1, []any{operation}})
	if err != nil {
		return nil, err
	}
	return &jobs.FixedBattleTemplate{ContractVersion: "fixed-battle-move-pool.v1", Request: encoded, AttackerMoves: sides[0].pool, DefenderMoves: sides[1].pool}, nil
}
