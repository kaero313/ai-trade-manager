import { describe, expect, it } from 'vitest'

import { resolveFirstTargetSymbol } from './laboratoryConfig'

describe('Strategy Laboratory 운영 대상 기본값', () => {
  it('SystemConfig 대상 목록의 첫 종목을 정규화한다', () => {
    expect(resolveFirstTargetSymbol('[" krw-eth ","KRW-BTC"]')).toBe('KRW-ETH')
  })

  it('잘못된 legacy 값은 기본 market을 덮지 않는다', () => {
    expect(resolveFirstTargetSymbol('KRW-XRP')).toBeNull()
    expect(resolveFirstTargetSymbol('[]')).toBeNull()
  })
})
