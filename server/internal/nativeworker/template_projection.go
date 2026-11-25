package nativeworker

import (
	"errors"
	"pokemonbattleinference/server/internal/jobs"
)

// ProjectFixedBattleTemplate 为同步固定推演复用正式共享模板投影，保持所有非招式字节不变。
// template 必须非nil；item两侧必须是已由Core规范化的1..4个正序唯一ID且全部属于冻结池。
// 返回独立完整请求，不借用可变map、不计算能力/PP/概率；失败不退化为模板里的代表招式。
func ProjectFixedBattleTemplate(template *jobs.FixedBattleTemplate, item jobs.CaseDefinition) ([]byte, error) {
	if template == nil {
		return nil, errors.New("fixed battle template is required")
	}
	for _, ids := range [][]int{item.AttackerMoves, item.DefenderMoves} {
		if len(ids) < 1 || len(ids) > 4 {
			return nil, errors.New("fixed battle projection requires one to four moves per side")
		}
		previous := 0
		for _, id := range ids {
			if id <= previous {
				return nil, errors.New("fixed battle projection requires positive sorted unique move ids")
			}
			previous = id
		}
	}
	projector, err := newRequestProjector(template)
	if err != nil {
		return nil, err
	}
	return projector.request(item)
}
