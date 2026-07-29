import { describe, expect, it } from 'vitest'

import {
  isTradingModeConfigKey,
  parseConfigApprovalRequest,
  TRADING_MODE_CONTROL_GUIDANCE,
} from './chatApprovalPolicy'

describe('AI Banker 설정 승인 보호 정책', () => {
  it('대소문자와 공백에 관계없이 trading_mode 승인을 보호한다', () => {
    expect(isTradingModeConfigKey('trading_mode')).toBe(true)
    expect(isTradingModeConfigKey('  TRADING_MODE  ')).toBe(true)
    expect(isTradingModeConfigKey('live_buy_enabled')).toBe(false)
    expect(TRADING_MODE_CONTROL_GUIDANCE).toContain('Bot Control')
  })

  it('승인 요청의 제안 시점 값과 version을 함께 파싱한다', () => {
    expect(
      parseConfigApprovalRequest(JSON.stringify({
        action: 'config_change',
        config_key: 'ai_entry_score_threshold',
        new_value: '65',
        current_value: '60',
        expected_version: 9,
        requires_approval: true,
      })),
    ).toEqual({
      action: 'config_change',
      config_key: 'ai_entry_score_threshold',
      new_value: '65',
      current_value: '60',
      expected_version: 9,
      requires_approval: true,
    })
  })

  it('version이 없거나 잘못된 승인 요청은 최신 UI 값으로 대체하지 않는다', () => {
    expect(
      parseConfigApprovalRequest(JSON.stringify({
        action: 'config_change',
        config_key: 'ai_entry_score_threshold',
        new_value: '65',
        current_value: '60',
        requires_approval: true,
      })),
    ).toBeNull()
    expect(
      parseConfigApprovalRequest(JSON.stringify({
        action: 'config_change',
        config_key: 'ai_entry_score_threshold',
        new_value: '65',
        current_value: '60',
        expected_version: 0,
        requires_approval: true,
      })),
    ).toBeNull()
  })
})
