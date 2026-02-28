from __future__ import annotations
import asyncpg
from typing import Any, Optional, Sequence
from datetime import datetime, date, time
import json
from pathlib import Path

class DB:
    def __init__(self, dsn: str):
        self.dsn = dsn
        self.pool: asyncpg.Pool | None = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=10)

    async def close(self):
        if self.pool:
            await self.pool.close()

    async def execute_sql_file(self, path: str):
        assert self.pool
        sql = Path(path).read_text(encoding="utf-8")
        async with self.pool.acquire() as con:
            await con.execute(sql)

    # ---------- Consent ----------
    async def has_consent(self, telegram_user_id: int) -> bool:
        assert self.pool
        row = await self.pool.fetchrow(
            "SELECT 1 FROM user_consents WHERE telegram_user_id=$1",
            telegram_user_id,
        )
        return row is not None

    async def add_consent(self, telegram_user_id: int, consented_at: datetime):
        assert self.pool
        # idempotent via ON CONFLICT
        await self.pool.execute(
            """INSERT INTO user_consents(telegram_user_id, consented_at)
                 VALUES ($1, $2)
                 ON CONFLICT (telegram_user_id) DO NOTHING""",
            telegram_user_id, consented_at
        )

    # ---------- Admin ----------
    async def seed_admins_from_env(self, admin_ids: list[int]):
        if not admin_ids:
            return
        assert self.pool
        async with self.pool.acquire() as con:
            async with con.transaction():
                for aid in admin_ids:
                    await con.execute(
                        "INSERT INTO admin_users(telegram_user_id) VALUES ($1) ON CONFLICT DO NOTHING",
                        aid
                    )

    async def is_admin(self, telegram_user_id: int) -> bool:
        assert self.pool
        row = await self.pool.fetchrow(
            "SELECT 1 FROM admin_users WHERE telegram_user_id=$1",
            telegram_user_id
        )
        return row is not None

    # ---------- Services ----------
    async def seed_services(self):
        """Seed MVP categories and services if empty."""
        assert self.pool
        async with self.pool.acquire() as con:
            async with con.transaction():
                cnt = await con.fetchval("SELECT COUNT(*) FROM service_categories")
                if cnt and cnt > 0:
                    return
                # categories
                сант = await con.fetchval(
                    "INSERT INTO service_categories(name) VALUES ($1) RETURNING id",
                    "Сантехнические работы"
                )
                слес = await con.fetchval(
                    "INSERT INTO service_categories(name) VALUES ($1) RETURNING id",
                    "Слесарные работы"
                )
                await con.execute(
                    """INSERT INTO services(category_id, name, price_rub, duration_min, sort_order)
                         VALUES
                         ($1, 'Замена смесителя', 1000, 120, 10),
                         ($2, 'Повесить полку', 1000, 120, 10)""",
                    сант, слес
                )

    async def list_categories(self) -> list[tuple[int,str]]:
        assert self.pool
        rows = await self.pool.fetch(
            "SELECT id, name FROM service_categories ORDER BY name"
        )
        return [(int(r["id"]), str(r["name"])) for r in rows]

    async def list_services_by_category(self, category_id: int) -> list[tuple[int,str,int,int,str]]:
        """returns (service_id, service_name, price, duration_min, category_name)"""
        assert self.pool
        rows = await self.pool.fetch(
            """SELECT s.id as service_id, s.name as service_name, s.price_rub, s.duration_min, c.name as category_name
                 FROM services s
                 JOIN service_categories c ON c.id = s.category_id
                 WHERE s.category_id=$1 AND s.is_active=true
                 ORDER BY s.sort_order, s.name""",
            category_id
        )
        out = []
        for r in rows:
            out.append((int(r["service_id"]), str(r["service_name"]), int(r["price_rub"]), int(r["duration_min"]), str(r["category_name"])))
        return out

    async def get_service_snapshot(self, service_id: int) -> tuple[int,str,int,int,str]:
        """returns (service_id, service_name, price, duration_min, category_name)"""
        assert self.pool
        r = await self.pool.fetchrow(
            """SELECT s.id as service_id, s.name as service_name, s.price_rub, s.duration_min, c.name as category_name
                 FROM services s
                 JOIN service_categories c ON c.id = s.category_id
                 WHERE s.id=$1""",
            service_id
        )
        if not r:
            raise ValueError("Service not found")
        return (int(r["service_id"]), str(r["service_name"]), int(r["price_rub"]), int(r["duration_min"]), str(r["category_name"]))

    # ---------- Draft ----------
    async def get_draft(self, telegram_user_id: int) -> Optional[dict[str, Any]]:
        assert self.pool
        r = await self.pool.fetchrow(
            "SELECT payload FROM draft_requests WHERE telegram_user_id=$1",
            telegram_user_id
        )
        if not r:
            return None
        payload = r["payload"]

        if isinstance(payload, dict):
            return payload

        if isinstance(payload, str):
            decoded = json.loads(payload)
            if isinstance(decoded, dict):
                return decoded
            return None

        # Fallback for legacy/invalid values that cannot be used as a draft object.
        return None

    async def upsert_draft(self, telegram_user_id: int, payload: dict[str, Any]):
        assert self.pool
        await self.pool.execute(
            """INSERT INTO draft_requests(telegram_user_id, payload, updated_at)
                 VALUES ($1, $2::jsonb, NOW())
                 ON CONFLICT (telegram_user_id)
                 DO UPDATE SET payload=EXCLUDED.payload, updated_at=NOW()""",
            telegram_user_id, json.dumps(payload, ensure_ascii=False)
        )

    async def clear_draft(self, telegram_user_id: int):
        assert self.pool
        await self.pool.execute(
            "DELETE FROM draft_requests WHERE telegram_user_id=$1",
            telegram_user_id
        )

    # ---------- Requests ----------
    async def create_request(
        self,
        telegram_user_id: int,
        address_type: str,
        address_label: str,
        apartment: Optional[str],
        service_id: int,
        booking_date: date,
        slots: list[tuple[time,time]],
        full_name: str,
        phone: str,
    ) -> int:
        assert self.pool
        service_id2, service_name, price, duration, category_name = await self.get_service_snapshot(service_id)
        async with self.pool.acquire() as con:
            async with con.transaction():
                # upsert profile
                await con.execute(
                    """INSERT INTO user_profiles(telegram_user_id, full_name, phone, updated_at)
                         VALUES ($1, $2, $3, NOW())
                         ON CONFLICT (telegram_user_id)
                         DO UPDATE SET full_name=EXCLUDED.full_name, phone=EXCLUDED.phone, updated_at=NOW()""",
                    telegram_user_id, full_name, phone
                )
                rid = await con.fetchval(
                    """INSERT INTO requests(
                            telegram_user_id, address_type, address_label, apartment,
                            service_id, service_name_snapshot, category_name_snapshot, price_snapshot_rub,
                            booking_date, status, awaiting_rating, created_at, updated_at
                         )
                         VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,'CREATED', false, NOW(), NOW())
                         RETURNING id""",
                    telegram_user_id, address_type, address_label, apartment,
                    service_id2, service_name, category_name, price,
                    booking_date
                )
                for a,b in slots:
                    await con.execute(
                        "INSERT INTO request_time_slots(request_id, time_from, time_to) VALUES ($1,$2,$3)",
                        rid, a, b
                    )
        return int(rid)

    async def set_request_group_message(self, request_id: int, group_chat_id: int, group_message_id: int):
        assert self.pool
        await self.pool.execute(
            "UPDATE requests SET group_chat_id=$2, group_message_id=$3, updated_at=NOW() WHERE id=$1",
            request_id, group_chat_id, group_message_id
        )

    async def get_request(self, request_id: int) -> Optional[dict[str, Any]]:
        assert self.pool
        r = await self.pool.fetchrow(
            "SELECT * FROM requests WHERE id=$1",
            request_id
        )
        if not r:
            return None
        return dict(r)

    async def get_request_slots(self, request_id: int) -> list[tuple[str,str]]:
        assert self.pool
        rows = await self.pool.fetch(
            "SELECT time_from, time_to FROM request_time_slots WHERE request_id=$1 ORDER BY time_from",
            request_id
        )
        return [(str(r["time_from"])[:5], str(r["time_to"])[:5]) for r in rows]

    async def get_request_rating(self, request_id: int) -> Optional[dict[str, Any]]:
        assert self.pool
        r = await self.pool.fetchrow("SELECT * FROM request_ratings WHERE request_id=$1", request_id)
        return dict(r) if r else None

    async def update_status(self, request_id: int, status: str):
        assert self.pool
        awaiting = True if status == "DONE" else False
        # If archived by admin, awaiting_rating should be false
        if status in ("ARCHIVED", "IN_PROGRESS", "CREATED"):
            awaiting = False
        await self.pool.execute(
            "UPDATE requests SET status=$2, awaiting_rating=$3, updated_at=NOW() WHERE id=$1",
            request_id, status, awaiting
        )

    async def add_rating(self, request_id: int, stars: int, comment: Optional[str]):
        assert self.pool
        await self.pool.execute(
            """INSERT INTO request_ratings(request_id, stars, comment)
                 VALUES ($1,$2,$3)
                 ON CONFLICT (request_id) DO NOTHING""",
            request_id, stars, comment
        )
        await self.pool.execute(
            "UPDATE requests SET status='ARCHIVED', awaiting_rating=false, updated_at=NOW() WHERE id=$1",
            request_id
        )
