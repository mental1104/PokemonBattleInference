package jobs

import (
	"errors"
	"strings"
)

// PreparationFailure 冻结原父协调器在准备具体配置时遇到的确定输入错误，不包含虚构战斗状态或结果。
// Code 只允许原 invalid_configuration；Diagnostic 保留原异常类型与消息，worker 领取后按正常 case lease 落 failed。
type PreparationFailure struct {
	Code       string `json:"failure_code"`
	Diagnostic string `json:"diagnostic"`
}

// Validate 拒绝伪装成准备失败的运行/取消错误；receiver 是只读冻结事实，不执行数据库或计算。
func (failure PreparationFailure) Validate() error {
	if failure.Code != "invalid_configuration" || strings.TrimSpace(failure.Diagnostic) == "" {
		return errors.New("frozen preparation failure requires invalid_configuration and a diagnostic")
	}
	return nil
}
