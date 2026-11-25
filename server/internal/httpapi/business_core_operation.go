package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"pokemonbattleinference/server/internal/workerprocess"
)

// nativeBusinessRejection 只保留完整ABI已验证invalid_input业务诊断，不携带stderr或进程路径。
type nativeBusinessRejection struct{ message string }

// Error 返回Core原领域诊断，由明确需要原文的业务边界用JSON安全编码。
func (failure *nativeBusinessRejection) Error() string { return failure.message }

// executeBusinessCoreOperation 是单操作JSON传输边界；业务caller在进入此函数前持有自己的具体DTO。
// ctx负责独立child取消/回收；只有完整ABI invalid_input可交付原业务message，其余失败保留现有隔离合同。
func executeBusinessCoreOperation(ctx context.Context, handler calculatorHandler, operation any) (json.RawMessage, error) {
	if !filepath.IsAbs(handler.worker) {
		return nil, errCalculatorWorkerUnavailable
	}
	info, err := os.Stat(handler.worker)
	if err != nil || !info.Mode().IsRegular() || info.Mode().Perm()&0111 == 0 {
		return nil, errCalculatorWorkerUnavailable
	}
	body, err := json.Marshal(struct {
		Version    int   `json:"schema_version"`
		Operations []any `json:"operations"`
	}{1, []any{operation}})
	if err != nil {
		return nil, err
	}
	raw, err := workerprocess.Execute(ctx, handler.worker, body)
	if err != nil {
		var failure *workerprocess.Failure
		if errors.As(err, &failure) && failure.Code == "invalid_input" {
			var native struct {
				Error struct {
					Code    string `json:"code"`
					Message string `json:"message"`
				} `json:"error"`
			}
			if json.Unmarshal(raw, &native) == nil && native.Error.Code == failure.Code && native.Error.Message != "" {
				return nil, &nativeBusinessRejection{native.Error.Message}
			}
		}
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		if !errors.As(err, &failure) && !errors.Is(err, workerprocess.ErrOutputLimit) {
			return nil, errCalculatorWorkerUnavailable
		}
		return nil, err
	}
	var response businessCoreBatch
	if json.Unmarshal(raw, &response) != nil || response.Version != 1 || len(response.Results) != 1 {
		return nil, errors.New("invalid native business operation envelope")
	}
	return response.Results[0], nil
}
