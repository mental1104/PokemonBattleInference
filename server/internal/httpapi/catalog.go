package httpapi

import (
	"database/sql"
	"encoding/json"
	"errors"
	"net/http"
	"pokemonbattleinference/server/internal/catalog"
	"strconv"
)

// registerCatalog 绑定已迁移的六条知识查询 API，沿用旧规则集与分页默认值。
func registerCatalog(mux *http.ServeMux, db *sql.DB) {
	store := catalog.New(db)
	mux.HandleFunc("GET /v1/calculator/pokemon", func(w http.ResponseWriter, r *http.Request) {
		limit, ok := queryInt(w, r, "limit", 20, 1, 50)
		if !ok {
			return
		}
		data, err := store.PokemonJSON(r.Context(), ruleset(r), r.URL.Query().Get("query"), limit, 0, false)
		catalogResponse(w, data, err)
	})
	mux.HandleFunc("GET /v1/calculator/pokemon/{pokemon_id}", func(w http.ResponseWriter, r *http.Request) {
		id, ok := pokemonID(w, r)
		if !ok {
			return
		}
		data, err := store.PokemonJSON(r.Context(), ruleset(r), "", 1, id, true)
		catalogResponse(w, data, err)
	})
	mux.HandleFunc("GET /v1/calculator/pokemon/{pokemon_id}/abilities", func(w http.ResponseWriter, r *http.Request) {
		id, ok := pokemonID(w, r)
		if !ok {
			return
		}
		data, err := store.Abilities(r.Context(), ruleset(r), id)
		catalogResponse(w, data, err)
	})
	mux.HandleFunc("GET /v1/calculator/pokemon/{pokemon_id}/moves", func(w http.ResponseWriter, r *http.Request) {
		id, ok := pokemonID(w, r)
		if !ok {
			return
		}
		limit, ok := queryInt(w, r, "limit", 10, 1, 50)
		if !ok {
			return
		}
		offset, ok := queryInt(w, r, "offset", 0, 0, 2147483647)
		if !ok {
			return
		}
		category := r.URL.Query().Get("category")
		if category == "" {
			category = "all"
		}
		if category != "all" && category != "physical" && category != "special" {
			detail(w, 422, "invalid move category")
			return
		}
		page, err := store.Moves(r.Context(), ruleset(r), id, r.URL.Query().Get("query"), category, r.URL.Query()["type"], limit, offset)
		if errors.Is(err, catalog.ErrInvalidFilter) {
			detail(w, 400, err.Error())
			return
		}
		if err != nil {
			detail(w, 503, "catalog storage unavailable")
			return
		}
		writeJSON(w, 200, page)
	})
	mux.HandleFunc("GET /v1/calculator/items", func(w http.ResponseWriter, r *http.Request) {
		data, err := store.Items(r.Context(), ruleset(r))
		catalogResponse(w, data, err)
	})
	mux.HandleFunc("GET /v1/calculator/presets", func(w http.ResponseWriter, r *http.Request) { writeJSON(w, 200, legacyPresets) })
}

// catalogResponse 将成功数据和缺失对象区分处理，禁止 SQL 错误泄露到客户端。
func catalogResponse(w http.ResponseWriter, data json.RawMessage, err error) {
	if errors.Is(err, sql.ErrNoRows) {
		detail(w, 404, "pokemon not found in ruleset")
		return
	}
	if err != nil {
		detail(w, 503, "catalog storage unavailable")
		return
	}
	writeJSON(w, 200, data)
}

// ruleset 返回旧服务默认规则集；显式未知值交给真实查询决定结果。
func ruleset(r *http.Request) string {
	value := r.URL.Query().Get("ruleset_id")
	if value == "" {
		return "pokemon-champion"
	}
	return value
}

// pokemonID 校验路径参数为正整数，失败写入旧框架同类的 422。
func pokemonID(w http.ResponseWriter, r *http.Request) (int, bool) {
	id, err := strconv.Atoi(r.PathValue("pokemon_id"))
	if err != nil || id <= 0 {
		detail(w, 422, "pokemon_id must be positive")
		return 0, false
	}
	return id, true
}

// queryInt 读取 name 的有界整数值，缺省采用 fallback，失败直接写入 422。
func queryInt(w http.ResponseWriter, r *http.Request, name string, fallback, min, max int) (int, bool) {
	raw := r.URL.Query().Get(name)
	if raw == "" {
		return fallback, true
	}
	value, err := strconv.Atoi(raw)
	if err != nil || value < min || value > max {
		detail(w, 422, "invalid "+name)
		return 0, false
	}
	return value, true
}

// preset 保留旧应用模板说明，数值计算仍由唯一 C++ Core 执行。
type preset struct {
	Key        string `json:"key"`
	Label      string `json:"label"`
	Assumption string `json:"assumption"`
}

var legacyPresets = map[string][]preset{
	"attacker": {{"no_investment", "无投入", "50 级 · 0 EV · 中性性格"}, {"max_atk_neutral", "满攻", "50 级 · 252 Atk · 中性性格"}, {"max_atk_plus", "极攻", "50 级 · 252 Atk · 攻击性格"}, {"max_spatk_neutral", "满特攻", "50 级 · 252 SpA · 中性性格"}, {"max_spatk_plus", "极特攻", "50 级 · 252 SpA · 特攻性格"}},
	"defender": {{"no_investment", "无投入", "50 级 · 0 EV · 中性性格"}, {"max_hp", "满 HP", "50 级 · 252 HP · 防御/特防无投入"}, {"max_hp_def", "物耐", "50 级 · 252 HP / 252 Def · 中性性格"}, {"max_hp_def_plus", "极限物耐", "50 级 · 252 HP / 252 Def · 防御性格"}, {"max_hp_spdef", "特耐", "50 级 · 252 HP / 252 SpD · 中性性格"}, {"max_hp_spdef_plus", "极限特耐", "50 级 · 252 HP / 252 SpD · 特防性格"}},
}
