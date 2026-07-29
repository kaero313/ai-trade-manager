import { describe, expect, it } from 'vitest'

import {
  attachEditBaseVersions,
  SystemConfigEditConflictError,
} from './systemConfigEditSnapshot'

const pendingUpdate = {
  config_key: 'max_allocation_pct',
  config_value: '25',
}

describe('SystemConfig 편집 기준 version', () => {
  it('최초 편집 version을 expected_version으로 고정한다', () => {
    expect(
      attachEditBaseVersions(
        [pendingUpdate],
        [
          {
            id: 1,
            config_key: 'max_allocation_pct',
            config_value: '30',
            description: null,
            version: 3,
          },
        ],
        { max_allocation_pct: 3 },
      ),
    ).toEqual([{ ...pendingUpdate, expected_version: 3 }])
  })

  it('편집 후 query가 version 4로 갱신돼도 새 version으로 재기반하지 않는다', () => {
    expect(() =>
      attachEditBaseVersions(
        [pendingUpdate],
        [
          {
            id: 1,
            config_key: 'max_allocation_pct',
            config_value: '30',
            description: null,
            version: 4,
          },
        ],
        { max_allocation_pct: 3 },
      ),
    ).toThrow(SystemConfigEditConflictError)
  })
})
