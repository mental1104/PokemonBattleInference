package workerprocess

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"os/exec"
	"path/filepath"
	"pokemonbattleinference/server/internal/corebridge"
)

// ErrProgressProtocol 表示子进程没有遵守有界进度帧和唯一末尾结果合同。
var ErrProgressProtocol = errors.New("invalid worker progress protocol")

const maxProgressFrames = 65536
const maxProgressBytes = 64 << 20

// progressFrame 只属于 Worker 传输边界，response 保持完整正式 ABI JSON，不重复业务 schema。
type progressFrame struct {
	Kind     string               `json:"kind"`
	Progress *corebridge.Progress `json:"progress,omitempty"`
	Response json.RawMessage      `json:"response,omitempty"`
}

// frameReader 维护一次子进程流的有界状态；result 必须唯一且是末帧，读取结束前不交付成功。
type frameReader struct {
	frames   int
	bytes    int
	result   []byte
	finished bool
}

// accept 校验一行完整 frame，返回可空的进度拥有值；line 不保留，非法或超限时不改变最终结果。
func (reader *frameReader) accept(line []byte) (*corebridge.Progress, error) {
	reader.frames++
	reader.bytes += len(line) + 1
	if reader.frames > maxProgressFrames || reader.bytes > maxProgressBytes {
		return nil, ErrOutputLimit
	}
	if reader.finished {
		return nil, ErrProgressProtocol
	}
	var frame progressFrame
	decoder := json.NewDecoder(bytes.NewReader(line))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&frame); err != nil {
		return nil, ErrProgressProtocol
	}
	if err := decoder.Decode(new(json.RawMessage)); err != io.EOF {
		return nil, ErrProgressProtocol
	}
	switch frame.Kind {
	case "progress":
		if len(line) > 1024 || frame.Progress == nil || len(frame.Response) != 0 {
			return nil, ErrProgressProtocol
		}
		if frame.Progress.Phase != corebridge.ProgressBuilding && frame.Progress.Phase != corebridge.ProgressBuilt {
			return nil, ErrProgressProtocol
		}
		if frame.Progress.OperationIndex >= corebridge.MaxOperations || frame.Progress.Nodes > corebridge.MaxGeneratedNodes ||
			frame.Progress.Edges > corebridge.MaxGeneratedEdges || frame.Progress.Expanded > frame.Progress.Nodes || frame.Progress.Frontier > frame.Progress.Nodes {
			return nil, ErrProgressProtocol
		}
		return frame.Progress, nil
	case "result":
		if frame.Progress != nil || len(frame.Response) == 0 || frame.Response[0] != '{' || !json.Valid(frame.Response) {
			return nil, ErrProgressProtocol
		}
		if len(frame.Response) > corebridge.MaxResultBytes {
			return nil, ErrOutputLimit
		}
		reader.result = append([]byte(nil), frame.Response...)
		reader.finished = true
		return nil, nil
	default:
		return nil, ErrProgressProtocol
	}
}

// ExecuteWithProgress 以显式 --progress 启动绝对 executable，逐行接收真实计数和唯一完整结果。
// ctx 取消/协议错误/超限会终止并回收本次子进程；request 借用到返回，不执行 shell。
// onProgress 可空，同步收到拥有值，必须快速返回；可复制到有界 latest 槽，由外部主循环写 PG。
// 返回完整独立结果和旧 Execute 相同 Failure 分类；任何进度或末帧缺失均不冒充成功。
func ExecuteWithProgress(ctx context.Context, executable string, request []byte, onProgress func(corebridge.Progress)) ([]byte, error) {
	if !filepath.IsAbs(executable) {
		return nil, errors.New("worker executable must be absolute")
	}
	if len(request) > corebridge.MaxRequestBytes {
		return nil, &Failure{Code: "resource_limit", ExitCode: 3}
	}
	diagnostic := limitedBuffer{max: 4 << 10}
	command := exec.CommandContext(ctx, executable, "--progress")
	command.Stdin = bytes.NewReader(request)
	command.Stderr = &diagnostic
	output, err := command.StdoutPipe()
	if err != nil {
		return nil, err
	}
	if err = command.Start(); err != nil {
		return nil, err
	}
	waited := false
	// 即使调用方回调 panic，也先回收该子进程；不让测试/任务留下孤儿 Worker。
	defer func() {
		if !waited {
			_ = command.Process.Kill()
			_ = command.Wait()
		}
	}()
	reader := frameReader{}
	scanner := bufio.NewScanner(output)
	scanner.Buffer(make([]byte, 64<<10), corebridge.MaxResultBytes+1024)
	var protocolError error
	for scanner.Scan() {
		progress, frameError := reader.accept(scanner.Bytes())
		if frameError != nil {
			protocolError = frameError
			break
		}
		if progress != nil && onProgress != nil {
			onProgress(*progress)
		}
	}
	if scanner.Err() != nil {
		protocolError = ErrOutputLimit
	}
	if protocolError != nil {
		_ = command.Process.Kill()
	}
	err = command.Wait()
	waited = true
	if ctx.Err() != nil {
		return reader.result, ctx.Err()
	}
	if protocolError != nil {
		return nil, protocolError
	}
	if err == nil {
		if !reader.finished {
			return nil, ErrProgressProtocol
		}
		return reader.result, nil
	}
	var exit *exec.ExitError
	if errors.As(err, &exit) {
		return reader.result, classifyExit(exit.ExitCode(), reader.result)
	}
	return nil, err
}
