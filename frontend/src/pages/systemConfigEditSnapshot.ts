import type { SystemConfigItem, SystemConfigUpdateItem } from '../services/api'

export type PendingSystemConfigUpdate = Omit<SystemConfigUpdateItem, 'expected_version'>
export type SystemConfigBaseVersions = Readonly<Record<string, number>>

export class SystemConfigEditSnapshotError extends Error {}

export class SystemConfigEditConflictError extends SystemConfigEditSnapshotError {}

export function attachEditBaseVersions(
  pendingUpdates: PendingSystemConfigUpdate[],
  items: SystemConfigItem[] | undefined,
  baseVersions: SystemConfigBaseVersions,
): SystemConfigUpdateItem[] {
  const configsByKey = new Map((items ?? []).map((item) => [item.config_key, item]))
  return pendingUpdates.map((update) => {
    const current = configsByKey.get(update.config_key)
    const baseVersion = baseVersions[update.config_key]
    if (!current || !Number.isInteger(current.version) || current.version < 1) {
      throw new SystemConfigEditSnapshotError(
        `${update.config_key} 설정의 현재 버전을 확인할 수 없습니다. 다시 조회해 주세요.`,
      )
    }
    if (!Number.isInteger(baseVersion) || baseVersion < 1) {
      throw new SystemConfigEditSnapshotError(
        `${update.config_key} 설정의 편집 기준 버전을 확인할 수 없습니다. 다시 편집해 주세요.`,
      )
    }
    if (current.version !== baseVersion) {
      throw new SystemConfigEditConflictError(
        `${update.config_key} 설정이 편집 중 변경되었습니다. ` +
          `(base=${baseVersion}, current=${current.version})`,
      )
    }
    return {
      ...update,
      expected_version: baseVersion,
    }
  })
}
