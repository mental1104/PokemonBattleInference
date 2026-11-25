package httpapi

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"net/http"
	"strings"
	"time"

	"pokemonbattleinference/server/internal/jobs"
)

// configurationCaseGraphHandler 从原持久化case身份读取选择，再按当前知识重建唯一Core图。
// graph与其他图入口共享同一个TTL缓存；不读取Go冻结模板或复用已存结果中的概率。
type configurationCaseGraphHandler struct {
	store *jobs.Store
	graph inferenceGraphHandler
}

// registerConfigurationCaseGraph 挂接原已成功配置的按需完整图路由。
// mux/db/fixed/store由服务器拥有；这里只构造只读仓库适配，不创建后台任务或另一图缓存。
func registerConfigurationCaseGraph(mux *http.ServeMux, db *sql.DB, fixed fixedInferenceHandler, store *inferenceGraphStore) {
	handler := configurationCaseGraphHandler{jobs.New(db), inferenceGraphHandler{fixed, store}}
	mux.Handle("POST /v1/inference/configuration-jobs/{job_id}/configurations/{configuration_id}/graph", handler)
}

// decodeConfigurationGraph 机械解码原六字段/双方七字段canonical数组，不产生新身份或排序招式。
// value是已查到的原pair ID；返回完整双方选择，原form/不同等级均保留给调用方按旧顺序处理。
func decodeConfigurationGraph(value string) ([2]inferenceChosenSide, error) {
	var result [2]inferenceChosenSide
	if _, err := configurationPokemonIDs(value); err != nil {
		return result, err
	}
	var payload []json.RawMessage
	if err := json.Unmarshal([]byte(strings.TrimPrefix(value, "one-on-one-configuration:")), &payload); err != nil {
		return result, err
	}
	for index := range result {
		var fields []json.RawMessage
		if err := json.Unmarshal(payload[4+index], &fields); err != nil {
			return result, err
		}
		side := &result[index]
		// 字段位置属于原canonical合同；每个类型/值已由只读身份解析检查，不做能力或机制裁定。
		for position, target := range []any{&side.PokemonID, &side.FormID, &side.Level, &side.Profile, &side.Ability, &side.Item, &side.Moves} {
			if err := json.Unmarshal(fields[position], target); err != nil {
				return result, err
			}
		}
	}
	return result, nil
}

// ServeHTTP 保持原job→execution spec→精确pair→成功状态→canonical/form→当前知识的检查顺序。
// r正文在原接口没有用途；ctx含30秒上限，覆盖读取、独立Core执行与缓存发布。只有完整图成功才写200。
func (handler configurationCaseGraphHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	ctx, cancel := context.WithTimeout(r.Context(), 30*time.Second)
	defer cancel()
	id, pair := r.PathValue("job_id"), r.PathValue("configuration_id")
	job, err := handler.store.GraphJob(ctx, id)
	if err != nil {
		if errors.Is(err, jobs.ErrExecutionSpecNotFound) {
			writeJSON(w, 404, map[string]any{"detail": map[string]string{"code": "battle_inference_job_not_found", "message": "battle inference execution spec for " + pythonRepr(id) + " does not exist"}})
		} else if ctx.Err() != nil {
			calculatorFailure(w, ctx.Err())
		} else {
			configurationJobError(w, id, err)
		}
		return
	}
	cases, _, err := handler.store.FilteredCases(ctx, id, jobs.CaseFilter{ConfigurationID: pair, Limit: 3})
	if err != nil {
		if ctx.Err() != nil {
			calculatorFailure(w, ctx.Err())
		} else {
			configurationJobError(w, id, err)
		}
		return
	}
	var selected *jobs.Case
	for index := range cases {
		if cases[index].Definition.PairID == pair {
			selected = &cases[index]
			break
		}
	}
	if selected == nil {
		detail(w, 404, "configuration does not exist in job")
		return
	}
	if selected.Status != jobs.Succeeded {
		detail(w, 409, "only a succeeded configuration can generate a full graph")
		return
	}
	sides, err := decodeConfigurationGraph(pair)
	if err != nil {
		// 原已存损坏canonical在HTTP捕获范围外失败；不将其当资料缺失或伪造默认配置。
		configurationGraphInternalError(w)
		return
	}
	if sides[0].FormID != nil || sides[1].FormID != nil {
		detail(w, 422, "explicit form_id is not supported yet")
		return
	}
	// 原_fixed_selection不传各侧level，rules.level仅取攻击者；不能改成双方各自canonical level。
	sides[1].Level = sides[0].Level
	input := inferenceFixedRequest{Ruleset: job.RulesetID, Version: job.VersionGroupID, Attacker: &sides[0], Defender: &sides[1],
		AttackerPolicy: job.Spec.AttackerPolicy, DefenderPolicy: job.Spec.DefenderPolicy,
		Limits: inferenceLimits{Nodes: job.Spec.MaxNodes, Edges: job.Spec.MaxEdges}}
	if job.Spec.MaxTurns != nil {
		input.Limits.Turns = *job.Spec.MaxTurns
	}
	budget := jobExecutionBudget{MaxNodes: job.Spec.MaxNodes, MaxEdges: job.Spec.MaxEdges, MaxTurns: job.Spec.MaxTurns}
	prepared, err := handler.graph.fixed.prepareReference(ctx, input, budget)
	if err != nil {
		configurationCaseGraphFailure(w, err)
		return
	}
	journey, err := handler.graph.createPrepared(ctx, input, prepared)
	if err != nil {
		configurationCaseGraphFailure(w, err)
		return
	}
	writeJSON(w, 200, journey)
}

// configurationCaseGraphFailure 保留原直接reference用例ValueError的字符串detail。
// 基础设施/取消/图store错误仍沿共享适配；不把fixed公开路由的strict错误封套带到本入口。
func configurationCaseGraphFailure(w http.ResponseWriter, err error) {
	var invalid *inferenceRequestError
	if errors.As(err, &invalid) {
		if invalid.status == 404 {
			// 原reference的LoadProfileNotFound是LookupError，不在本route的ValueError捕获范围。
			configurationGraphInternalError(w)
			return
		}
		if invalid.status == 422 {
			detail(w, 422, invalid.message)
			return
		}
	}
	inferenceGraphFailure(w, err)
}

// configurationGraphInternalError 保留原未捕获旧资料/损坏身份的安全500响应，不输出底层异常或SQL。
// w只写一次原框架的plain文本；这是原合同差异记录，不伪装成新查询的成功结果。
func configurationGraphInternalError(w http.ResponseWriter) {
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	w.WriteHeader(500)
	_, _ = w.Write([]byte("Internal Server Error"))
}
