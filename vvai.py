import psutil
import time
import matplotlib.pyplot as plt
from datetime import datetime
import sys
import csv
from pynput import keyboard

# ================= CONFIGURATION =================
INTERVAL = 0.3  # 采样频率
# =================================================

# 修复中文显示
plt.rcParams['font.sans-serif'] = ['Arial Unicode MS', 'PingFang HK', 'Heiti TC', 'SimHei', 'sans-serif']
plt.rcParams['axes.unicode_minus'] = False

markers = []  # 存储(时间戳, 标记类型, 组ID)
last_marker = None


def on_press(key):
    global last_marker
    try:
        if key == keyboard.Key.enter:
            t_mark = time.time()
            count = len(markers)
            group_id = (count // 2) + 1
            if count % 2 == 0:
                label = f"M{group_id}-START"
                print(f"\n🚩 [M{group_id}] 开始测试...")
            else:
                label = f"M{group_id}-END"
                dur = t_mark - markers[-1][0]
                print(f"\n✅ [M{group_id}] 结束测试！区间耗时: {dur:.2f}s")
            markers.append((t_mark, label, group_id))
            last_marker = (t_mark, label, group_id)
    except Exception:
        pass


def get_ancestor_pids(proc):
    """递归获取进程的所有祖先PID（父、祖父...）"""
    ancestors = []
    try:
        ppid = proc.ppid()
        while ppid != 0:  # PID 0 是内核进程，终止递归
            ancestors.append(ppid)
            parent_proc = psutil.Process(ppid)
            ppid = parent_proc.ppid()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return ancestors


def get_lark_related_processes(main_keyword):
    """
    找到所有和Lark相关的进程（主进程+所有子/孙进程）
    1. 先找含关键词的主进程
    2. 再找所有以主进程为祖先的子进程
    """
    # 第一步：找Lark主进程PID
    main_pids = set()
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            if main_keyword.lower() in proc.info['name'].lower():
                main_pids.add(proc.info['pid'])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not main_pids:
        return []

    # 第二步：找所有主进程的子/孙进程
    lark_procs = []
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            # 进程本身是主进程，或祖先包含主进程 → 属于Lark相关进程
            if proc.info['pid'] in main_pids or any(p in main_pids for p in get_ancestor_pids(proc)):
                lark_procs.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return lark_procs


def get_aggregate_resources(main_keyword):
    """聚合所有Lark相关进程的资源（替换原有的仅名称匹配逻辑）"""
    t_cpu, t_mem, t_fds, t_threads, p_count = 0.0, 0.0, 0, 0, 0
    lark_procs = get_lark_related_processes(main_keyword)

    for proc in lark_procs:
        try:
            t_cpu += proc.cpu_percent(interval=None)
            t_mem += proc.memory_info().rss / (1024 * 1024)
            t_fds += proc.num_fds()
            t_threads += proc.num_threads()
            p_count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return t_cpu, t_mem, t_fds, t_threads, p_count


def start_monitoring(process_name):
    global last_marker
    print(f"📡 正在等待搜索进程: '{process_name}'（含所有子进程）...")
    while True:
        _, _, _, _, p_cnt = get_aggregate_resources(process_name)
        if p_cnt > 0:
            print(f"✅ 已锁定 {p_cnt} 个 {process_name} 相关进程（主进程+子进程）。")
            print("操作：按 Enter 标记测试开始/结束，Ctrl+C 停止监控。")
            break
        time.sleep(1)

    listener = keyboard.Listener(on_press=on_press)
    listener.start()

    data_log = []
    last_net = psutil.net_io_counters()
    start_time = time.time()
    last_t = start_time

    try:
        while True:
            time.sleep(INTERVAL)
            curr_t_real = time.time()
            delta_t = curr_t_real - last_t
            if delta_t <= 0: continue

            cpu, mem, fds, threads, p_cnt = get_aggregate_resources(process_name)
            curr_net = psutil.net_io_counters()
            up_s = ((curr_net.bytes_sent - last_net.bytes_sent) / 1024) / delta_t
            down_s = ((curr_net.bytes_recv - last_net.bytes_recv) / 1024) / delta_t

            last_net, last_t = curr_net, curr_t_real
            curr_t_rel = curr_t_real - start_time

            enter_marker = ""
            if last_marker is not None:
                mark_time, mark_label, group_id = last_marker
                if abs(curr_t_real - mark_time) < INTERVAL + 0.1:
                    enter_marker = mark_label
                    last_marker = None
            if enter_marker == "":
                for (mark_time, mark_label, _) in markers:
                    mark_time_rel = mark_time - start_time
                    if abs(curr_t_rel - mark_time_rel) < 0.5:
                        enter_marker = mark_label
                        break

            data_log.append({
                'Relative_Time(s)': round(curr_t_rel, 3),
                'CPU(%)': round(cpu, 2),
                'Memory(MB)': round(mem, 2),
                'FDs(Handles)': fds,
                'Threads': threads,
                'Upload(KB/s)': round(up_s, 2),
                'Download(KB/s)': round(down_s, 2),
                'Process_Count': p_cnt,
                'Enter_Marker': enter_marker
            })

            sys.stdout.write(f"\r[监视] 进程:{p_cnt} | CPU:{cpu:>5.1f}% | 句柄(FD):{fds:>4} | 线程:{threads:>3}")
            sys.stdout.flush()

            if p_cnt == 0 and len(data_log) > 20: break

    except KeyboardInterrupt:
        print("\n⏹ 手动停止记录。")

    if len(data_log) > 1:
        export_csv(data_log, process_name)

        t_l = [d['Relative_Time(s)'] for d in data_log]
        cpu_l = [d['CPU(%)'] for d in data_log]
        mem_l = [d['Memory(MB)'] for d in data_log]
        fds_l = [d['FDs(Handles)'] for d in data_log]
        thr_l = [d['Threads'] for d in data_log]
        up_l = [d['Upload(KB/s)'] for d in data_log]
        down_l = [d['Download(KB/s)'] for d in data_log]

        generate_final_report(t_l, cpu_l, mem_l, fds_l, thr_l, up_l, down_l,
                              [(m[0] - start_time, m[1], m[2]) for m in markers], process_name)


def export_csv(data, process_name):
    file_name = f"{process_name}_Data_{datetime.now().strftime('%H%M%S')}.csv"
    keys = data[0].keys()
    try:
        with open(file_name, 'w', newline='', encoding='utf-8-sig') as f:
            dict_writer = csv.DictWriter(f, fieldnames=keys)
            dict_writer.writeheader()
            dict_writer.writerows(data)
        print(f"\n📂 数据已导出至明细表: {file_name}")
    except Exception as e:
        print(f"\n❌ CSV 导出失败: {e}")


def generate_final_report(t, cpu, mem, fds, thr, up, down, rel_markers, process_name):
    print("📊 正在生成聚合性能分析报告...")
    fig, axes = plt.subplots(6, 1, figsize=(14, 22), sharex=True)

    dur_map = {}
    for i in range(0, len(rel_markers) - 1, 2):
        if "START" in rel_markers[i][1] and "END" in rel_markers[i + 1][1]:
            dur_map[rel_markers[i][2]] = (rel_markers[i][0], rel_markers[i + 1][0],
                                          rel_markers[i + 1][0] - rel_markers[i][0])

    titles = [
        'Aggregate CPU (%)',
        'Aggregate Memory (MB)',
        'File Descriptors (Unix Handles)',
        'Thread Count',
        'Global Upload (KB/s)',
        'Global Download (KB/s)'
    ]
    data_sets = [cpu, mem, fds, thr, up, down]
    colors = ['#1f77b4', '#d62728', '#2ca02c', '#9467bd', '#ff7f0e', '#17becf']

    main_title = f"{process_name} {datetime.now().strftime('%Y-%m-%d')} 指标监控报告 (macOS)"
    fig.suptitle(main_title, fontsize=26, fontweight='bold', y=0.98)

    for i in range(6):
        ax = axes[i]
        ax.plot(t, data_sets[i], color=colors[i], linewidth=1.5)
        if i in [0, 1, 4, 5]:
            ax.fill_between(t, data_sets[i], color=colors[i], alpha=0.1)
        ax.set_title(titles[i], loc='left', fontsize=12, fontweight='bold', pad=10)
        ax.grid(linestyle=':', alpha=0.5)

        for g_id, (t1, t2, dur) in dur_map.items():
            ax.axvspan(t1, t2, color='red', alpha=0.05)
            ax.axvline(x=t1, color='red', linestyle='--', alpha=0.5)
            ax.axvline(x=t2, color='green', linestyle='--', alpha=0.5)
            if i == 0:
                y_max = max(cpu or [10])
                ax.text((t1 + t2) / 2, y_max * 1.05, f"M{g_id}: {dur:.2f}s",
                        ha='center', fontweight='bold', bbox=dict(facecolor='#FFEB3B', alpha=0.8, edgecolor='none'))

    plt.tight_layout()
    fig.subplots_adjust(top=0.93, hspace=0.4)

    out_file = f"{process_name}_Performance_Audit_{datetime.now().strftime('%H%M%S')}.png"
    out_file = out_file.replace('/', '_').replace('\\', '_').replace(':', '_').replace('*', '_').replace('?',
                                                                                                         '_').replace(
        '"', '_').replace('<', '_').replace('>', '_').replace('|', '_')
    plt.savefig(out_file, dpi=300)
    print(f"✅ 视觉报告已生成: {out_file}")
    plt.show()


if __name__ == "__main__":
    print("======================================")
    print("      macOS 进程性能监控工具（支持子进程）")
    print("======================================")
    target_process = input("请输入要监控的主进程名称关键词（如Lark）: ").strip()
    if not target_process:
        print("❌ 进程名称不能为空！")
        sys.exit(1)
    print("--------------------------------------")
    start_monitoring(target_process)