package httpapi

import (
	"net/http/httptest"
	"strings"
	"testing"
)

// TestCalculatorSchemaRejectsBeforeDatabase 对照原 strict stages/必填/空值边界；未接 PG 证明拒绝发生于入口。
// t 管理每项非法外部正文；任何误接受会访问空仓库并失败，不能用虚假成功遮掩。
func TestCalculatorSchemaRejectsBeforeDatabase(t *testing.T) {
	for name, body := range map[string]string{
		"missing":          `{}`,
		"null body":        `null`,
		"missing move":     `{"attacker":{"pokemon_id":212,"stat_preset":"max_atk_plus","ability_identifier":"technician"},"defender":{"pokemon_id":242,"stat_preset":"max_hp","ability_identifier":"natural-cure"}}`,
		"null ruleset":     `{"ruleset_id":null,"move_id":418,"attacker":{"pokemon_id":212,"stat_preset":"max_atk_plus","ability_identifier":"technician"},"defender":{"pokemon_id":242,"stat_preset":"max_hp","ability_identifier":"natural-cure"}}`,
		"null level":       `{"move_id":418,"attacker":{"pokemon_id":212,"level":null,"stat_preset":"max_atk_plus","ability_identifier":"technician"},"defender":{"pokemon_id":242,"stat_preset":"max_hp","ability_identifier":"natural-cure"}}`,
		"level zero":       `{"move_id":418,"attacker":{"pokemon_id":212,"level":0,"stat_preset":"max_atk_plus","ability_identifier":"technician"},"defender":{"pokemon_id":242,"stat_preset":"max_hp","ability_identifier":"natural-cure"}}`,
		"null stages":      `{"move_id":418,"attacker":{"pokemon_id":212,"stat_preset":"max_atk_plus","ability_identifier":"technician","stat_stages":null},"defender":{"pokemon_id":242,"stat_preset":"max_hp","ability_identifier":"natural-cure"}}`,
		"null stage":       `{"move_id":418,"attacker":{"pokemon_id":212,"stat_preset":"max_atk_plus","ability_identifier":"technician","stat_stages":{"attack":null}},"defender":{"pokemon_id":242,"stat_preset":"max_hp","ability_identifier":"natural-cure"}}`,
		"boolean stage":    `{"move_id":418,"attacker":{"pokemon_id":212,"stat_preset":"max_atk_plus","ability_identifier":"technician","stat_stages":{"attack":true}},"defender":{"pokemon_id":242,"stat_preset":"max_hp","ability_identifier":"natural-cure"}}`,
		"fractional stage": `{"move_id":418,"attacker":{"pokemon_id":212,"stat_preset":"max_atk_plus","ability_identifier":"technician","stat_stages":{"attack":1.5}},"defender":{"pokemon_id":242,"stat_preset":"max_hp","ability_identifier":"natural-cure"}}`,
		"stage range":      `{"move_id":418,"attacker":{"pokemon_id":212,"stat_preset":"max_atk_plus","ability_identifier":"technician","stat_stages":{"attack":7}},"defender":{"pokemon_id":242,"stat_preset":"max_hp","ability_identifier":"natural-cure"}}`,
	} {
		t.Run(name, func(t *testing.T) {
			// 每个子场景只验证公共输入约束，不伪造数据库结果或任何战斗计算。
			response := httptest.NewRecorder()
			calculatorHandler{}.ServeHTTP(response, httptest.NewRequest("POST", "/v1/calculator/damage", strings.NewReader(body)))
			if response.Code != 422 {
				t.Fatalf("invalid request status=%d body=%s", response.Code, response.Body)
			}
		})
	}
}
