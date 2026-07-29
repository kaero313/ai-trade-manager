const TRADING_MODE_CONFIG_KEY = 'trading_mode'

export interface ConfigApprovalRequest {
  action: 'config_change'
  config_key: string
  new_value: string
  current_value: string
  expected_version: number
  requires_approval: true
}

export const TRADING_MODE_CONTROL_GUIDANCE =
  '거래 모드는 AI Banker 설정 승인으로 변경할 수 없습니다. 대시보드 Bot Control의 전용 거래 모드 제어를 사용해 주세요.'

export function isTradingModeConfigKey(value: string): boolean {
  return value.trim().toLowerCase() === TRADING_MODE_CONFIG_KEY
}

export function parseConfigApprovalRequest(content: string): ConfigApprovalRequest | null {
  if (!content.trim()) {
    return null
  }

  try {
    const parsed = JSON.parse(content) as Partial<ConfigApprovalRequest>
    if (
      parsed.action !== 'config_change' ||
      typeof parsed.config_key !== 'string' ||
      typeof parsed.new_value !== 'string' ||
      typeof parsed.current_value !== 'string' ||
      !Number.isInteger(parsed.expected_version) ||
      Number(parsed.expected_version) < 1 ||
      parsed.requires_approval !== true
    ) {
      return null
    }

    return {
      action: 'config_change',
      config_key: parsed.config_key,
      new_value: parsed.new_value,
      current_value: parsed.current_value,
      expected_version: Number(parsed.expected_version),
      requires_approval: true,
    }
  } catch {
    return null
  }
}
