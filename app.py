"""Streamlit entry point for the local BOSS job collection application."""

from __future__ import annotations

import os
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from boss_app.db import DEFAULT_DB_PATH, Database, uses_qualified_target
from boss_app.exporter import export_task_to_excel
from boss_app.login_manager import LoginManager, LoginState, LoginStatus
from boss_app.task_manager import RUN_MODE_LIMITS, TaskManager, resolve_job_limit
from scripts import boss_cdp_raw as core


load_dotenv()


st.set_page_config(page_title="BOSS 岗位采集", page_icon="📋", layout="wide")


@st.cache_resource
def get_services() -> tuple[Database, TaskManager, LoginManager]:
    database = Database(os.environ.get("BOSS_DB_PATH", str(DEFAULT_DB_PATH)))
    database.recover_interrupted()
    return database, TaskManager(database), LoginManager(database)


def _task_label(task: dict) -> str:
    created = str(task.get("created_at") or "").replace("T", " ")[:19]
    return f"{task['keyword']} · {task['city'] or '全国'} · {task['status']} · {created}"


def _find_current_job(database: Database, task_id: str, job_id: str | None) -> str:
    if not job_id:
        return "-"
    for job in database.list_jobs(task_id):
        if job["job_id"] == job_id:
            return job["job_name"] or job_id
    return job_id


def main() -> None:
    database, manager, login_manager = get_services()
    st.title("BOSS 直聘岗位采集")
    st.caption("本地运行 · 专用 Chrome Profile · SQLite 断点续跑 · AI 结构化 · Excel 导出")

    with st.sidebar:
        st.header("新建采集任务")
        with st.form("new_task"):
            keyword = st.text_input("岗位名称 *", value="AI运营")
            city = st.text_input("意向城市", value="全国")
            salary_name = st.selectbox("薪资范围", ["不限", *[name for name in core.SALARY_MAP if name != "不限"]])
            experience_name = st.selectbox(
                "工作经验", ["不限", *[name for name in core.EXPERIENCE_MAP if name != "不限"]]
            )
            degree_name = st.selectbox("学历要求", ["不限", *[name for name in core.DEGREE_MAP if name != "不限"]])
            run_mode_names = list(RUN_MODE_LIMITS)
            run_mode = st.selectbox(
                "分阶段运行模式",
                run_mode_names,
                index=run_mode_names.index("50条扩容测试"),
            )
            custom_jobs = st.number_input(
                "自定义岗位数量", min_value=1, max_value=10000, value=10,
                disabled=run_mode != "自定义数量",
            )
            max_pages = st.number_input(
                "最大抓取页数", min_value=1, max_value=core.MAX_PAGES, value=10,
            )
            submitted = st.form_submit_button("开始采集", type="primary", use_container_width=True)
        if submitted:
            if not keyword.strip():
                st.error("岗位名称不能为空")
            else:
                max_jobs = resolve_job_limit(run_mode, int(custom_jobs))
                task_id = database.create_task(
                    keyword=keyword,
                    city=city,
                    salary_filter="" if salary_name == "不限" else core.SALARY_MAP[salary_name],
                    experience_filter="" if experience_name == "不限" else core.EXPERIENCE_MAP[experience_name],
                    degree_filter="" if degree_name == "不限" else core.DEGREE_MAP[degree_name],
                    max_pages=int(max_pages),
                    max_jobs=max_jobs,
                    run_mode=run_mode,
                )
                st.session_state["active_task_id"] = task_id
                if manager.start(task_id):
                    st.success("采集任务已启动")
                else:
                    st.warning("已有任务正在运行，请稍后重试")

        st.divider()
        if st.button("打开登录浏览器", use_container_width=True):
            login_manager.open_login_browser()
            st.info("已启动 BOSS 专用 Chrome，请在其中完成登录")
        if st.button("检查登录状态", use_container_width=True):
            with st.spinner("正在检查登录状态…"):
                st.session_state["login_state"] = login_manager.status(probe=True)
        login_state = st.session_state.get(
            "login_state", LoginState(LoginStatus.UNKNOWN, "尚未检查")
        )
        st.write(f"登录状态：**{login_state.status.value}**")
        if login_state.message:
            st.caption(login_state.message)

    tasks = database.list_tasks()
    if not tasks:
        st.info("尚无任务。可从左侧创建首个采集任务。")
        return
    task_ids = [task["task_id"] for task in tasks]
    active_id = st.session_state.get("active_task_id")
    default_index = task_ids.index(active_id) if active_id in task_ids else 0
    selected_id = st.selectbox(
        "历史任务",
        task_ids,
        index=default_index,
        format_func=lambda value: _task_label(next(task for task in tasks if task["task_id"] == value)),
    )
    st.session_state["active_task_id"] = selected_id

    selected_task = database.get_task(selected_id)
    strategy_owned = bool(selected_task and selected_task["strategy_id"])
    existing_count = len(database.list_jobs(selected_id))
    selected_snapshot = manager.snapshot(selected_id)
    qualified_target = bool(
        selected_task
        and uses_qualified_target(selected_task["keyword"], selected_task["city"])
    )
    minimum_target = selected_snapshot["qualified"] if qualified_target else existing_count
    if selected_task and selected_task["status"] == "waiting_for_access":
        st.warning(
            "平台当前限制访问，任务已保存进度并停止所有后续请求。"
            "请暂停一段时间，确认平台恢复后再点击“恢复/继续任务”；程序不会自动循环重试。"
        )
    if strategy_owned:
        st.info(
            "这是策略任务。请通过 Codex Skill 或 `boss-jobs run` 按原策略恢复，"
            "以继续同一个 Run 和请求预算；普通 Streamlit worker 不会接管该任务。"
        )

    with st.expander("扩大或调整当前历史任务"):
        st.caption(
            f"当前已有 {existing_count} 条去重候选；全国 AI运营任务只把完整 JD "
            "经 AI 审核合格的岗位计入目标，所有候选仍保留用于去重。"
        )
        mode_names = list(RUN_MODE_LIMITS)
        current_mode = (selected_task or {}).get("run_mode", "自定义数量")
        mode_index = mode_names.index(current_mode) if current_mode in mode_names else len(mode_names) - 1
        with st.form("expand_task"):
            expanded_mode = st.selectbox("新的运行模式", mode_names, index=mode_index)
            expanded_custom_jobs = st.number_input(
                "新的自定义岗位数量", min_value=max(1, minimum_target), max_value=10000,
                value=max(minimum_target, int((selected_task or {}).get("max_jobs", 10))),
                disabled=expanded_mode != "自定义数量",
            )
            expanded_pages = st.number_input(
                "新的最大抓取页数", min_value=1, max_value=core.MAX_PAGES,
                value=int((selected_task or {}).get("max_pages", 1)),
            )
            expand_submitted = st.form_submit_button(
                "保存参数并从断点继续", disabled=strategy_owned,
            )
        if expand_submitted:
            try:
                expanded_jobs = resolve_job_limit(expanded_mode, int(expanded_custom_jobs))
                if expanded_jobs < minimum_target:
                    count_name = "已合格" if qualified_target else "已有"
                    raise ValueError(f"目标数量不能小于{count_name} {minimum_target} 条")
                if manager.expand(
                    selected_id, max_jobs=expanded_jobs,
                    max_pages=int(expanded_pages), run_mode=expanded_mode,
                ):
                    st.success(f"目标已更新为 {expanded_jobs} 条，并从现有进度继续")
                else:
                    st.warning("worker 尚未释放或已有其他任务运行")
            except (KeyError, RuntimeError, ValueError) as exc:
                st.error(f"任务扩容失败：{exc}")

    action_columns = st.columns(5)
    if action_columns[0].button("暂停任务", use_container_width=True):
        manager.pause(selected_id)
        st.info("已请求暂停，将在当前网络步骤结束后生效")
    if action_columns[1].button(
        "恢复/继续任务",
        use_container_width=True,
        disabled=strategy_owned,
    ):
        if manager.resume(selected_id):
            st.success("任务已继续")
        else:
            st.warning("worker 尚未释放或已有其他任务运行")
    if action_columns[2].button(
        "仅重试 AI", use_container_width=True, disabled=strategy_owned,
    ):
        if manager.retry_ai(selected_id):
            st.success("AI 重处理已启动")
        else:
            st.warning("已有任务正在运行")
    if action_columns[3].button(
        "导出 Excel", use_container_width=True, disabled=strategy_owned,
    ):
        try:
            output_path = export_task_to_excel(database, selected_id)
            st.session_state["excel_path"] = str(output_path)
            st.success(f"Excel 已生成：{output_path}")
        except (KeyError, OSError, ValueError) as exc:
            st.error(f"Excel 导出失败：{exc}")
    if action_columns[4].button("刷新状态", use_container_width=True):
        st.rerun()

    excel_path = Path(st.session_state.get("excel_path", ""))
    if excel_path.is_file():
        st.download_button(
            "下载 Excel",
            data=excel_path.read_bytes(),
            file_name=excel_path.name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            on_click="ignore",
        )

    @st.fragment(run_every="2s")
    def status_panel(task_id: str) -> None:
        snapshot = manager.snapshot(task_id)
        chrome_state = login_manager.status(probe=False)
        metrics = st.columns(7)
        metrics[0].metric("Chrome", chrome_state.status.value)
        metrics[1].metric("任务状态", snapshot["status"])
        metrics[2].metric("已发现", snapshot["discovered_count"])
        metrics[3].metric("去重后", snapshot["deduped"])
        metrics[4].metric("详情完成", snapshot["details_done"])
        metrics[5].metric("合格岗位", snapshot["qualified"])
        metrics[6].metric("不相关", snapshot["irrelevant"])
        lower = st.columns(4)
        lower[0].metric("失败数量", snapshot["failed"])
        lower[1].metric("最大页数", snapshot["max_pages"])
        lower[2].metric("最大岗位数", snapshot["max_jobs"])
        lower[3].metric("当前岗位", _find_current_job(database, task_id, snapshot["current_job_id"]))
        st.write(f"运行模式：{snapshot.get('run_mode') or '自定义数量'}")
        st.write(f"最近错误：{snapshot['error_message'] or '-'}")
        st.write(f"输出文件：{snapshot['output_path'] or '-'}")

    status_panel(selected_id)


if __name__ == "__main__":
    main()
