"""feat(db): 설정 버전과 봇 런타임 상태를 분리

Revision ID: d5e8a1c4b7f2
Revises: c7a1e9d4f2b6
Create Date: 2026-07-15 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d5e8a1c4b7f2"
down_revision: Union[str, Sequence[str], None] = "c7a1e9d4f2b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "bot_configs",
        sa.Column(
            "config_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )
    op.add_column(
        "bot_configs",
        sa.Column("runtime_last_heartbeat", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "bot_configs",
        sa.Column("runtime_last_error", sa.Text(), nullable=True),
    )
    op.add_column(
        "bot_configs",
        sa.Column("runtime_latest_action", sa.Text(), nullable=True),
    )
    op.add_column(
        "bot_configs",
        sa.Column("runtime_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "system_configs",
        sa.Column(
            "version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )

    # PostgreSQL 16의 입력 검증 함수를 사용해 잘못된 legacy 시각은 NULL로 격리합니다.
    # runtime_status만 제거하고 metadata의 다른 키는 그대로 보존합니다.
    op.execute(
        sa.text(
            """
            UPDATE bot_configs
            SET runtime_last_heartbeat = CASE
                    WHEN config_json #>> '{metadata,runtime_status,last_heartbeat}' IS NOT NULL
                     AND pg_input_is_valid(
                         config_json #>> '{metadata,runtime_status,last_heartbeat}',
                         'timestamp with time zone'
                     )
                    THEN (config_json #>> '{metadata,runtime_status,last_heartbeat}')::timestamptz
                    ELSE NULL
                END,
                runtime_last_error = config_json #>> '{metadata,runtime_status,last_error}',
                runtime_latest_action = config_json #>> '{metadata,runtime_status,latest_action}',
                runtime_updated_at = CASE
                    WHEN config_json #>> '{metadata,runtime_status,updated_at}' IS NOT NULL
                     AND pg_input_is_valid(
                         config_json #>> '{metadata,runtime_status,updated_at}',
                         'timestamp with time zone'
                     )
                    THEN (config_json #>> '{metadata,runtime_status,updated_at}')::timestamptz
                    ELSE NULL
                END,
                config_json = CASE
                    WHEN (
                        (config_json::jsonb #- '{metadata,runtime_status}')
                        -> 'metadata'
                    ) = '{}'::jsonb
                    THEN (
                        (config_json::jsonb #- '{metadata,runtime_status}')
                        - 'metadata'
                    )::json
                    ELSE (config_json::jsonb #- '{metadata,runtime_status}')::json
                END
            WHERE jsonb_typeof(
                config_json::jsonb #> '{metadata,runtime_status}'
            ) = 'object'
            """
        )
    )

    op.create_check_constraint(
        "ck_bot_configs_config_version",
        "bot_configs",
        "config_version >= 1",
    )
    op.create_check_constraint(
        "ck_system_configs_version",
        "system_configs",
        "version >= 1",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_system_configs_version",
        "system_configs",
        type_="check",
    )
    op.drop_constraint(
        "ck_bot_configs_config_version",
        "bot_configs",
        type_="check",
    )

    # 정상적인 객체형 설정만 legacy metadata.runtime_status 형태로 되돌립니다.
    # 객체가 아닌 비정상 metadata는 덮어쓰지 않아 원본 데이터를 보존합니다.
    op.execute(
        sa.text(
            """
            UPDATE bot_configs
            SET config_json = jsonb_set(
                config_json::jsonb,
                '{metadata}',
                COALESCE(
                    CASE
                        WHEN jsonb_typeof(config_json::jsonb -> 'metadata') = 'object'
                        THEN config_json::jsonb -> 'metadata'
                        ELSE NULL
                    END,
                    '{}'::jsonb
                ) || jsonb_build_object(
                    'runtime_status',
                    jsonb_build_object(
                        'last_heartbeat', runtime_last_heartbeat,
                        'last_error', runtime_last_error,
                        'latest_action', runtime_latest_action,
                        'updated_at', runtime_updated_at
                    )
                ),
                true
            )::json
            WHERE jsonb_typeof(config_json::jsonb) = 'object'
              AND (
                  config_json::jsonb -> 'metadata' IS NULL
                  OR jsonb_typeof(config_json::jsonb -> 'metadata') = 'object'
              )
            """
        )
    )

    op.drop_column("system_configs", "version")
    op.drop_column("bot_configs", "runtime_updated_at")
    op.drop_column("bot_configs", "runtime_latest_action")
    op.drop_column("bot_configs", "runtime_last_error")
    op.drop_column("bot_configs", "runtime_last_heartbeat")
    op.drop_column("bot_configs", "config_version")
