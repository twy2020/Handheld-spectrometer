# spectral_filter_and_plot.py
import os
import warnings
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# Try to import SciPy smoothing tools; provide fallbacks if not available
try:
    from scipy.signal import savgol_filter
    from scipy.interpolate import make_interp_spline
    SCIPY_AVAILABLE = True
except Exception:
    SCIPY_AVAILABLE = False

# ---------------------- 1. Basic Configuration ----------------------
DATA_PATH = "measurement_session_20251005_153547.csv"  # <- 替换为你的文件路径
ROOT_FOLDER = "measurement_curves_spectral_colors"
CONDITION_FOLDERS = ["LED Only", "UV Only", "LED+UV"]

CHANNEL_CONFIG = {
    "F1": {"range": "405-425nm", "color": "#9900ff", "name": "Violet"},
    "F2": {"range": "435-455nm", "color": "#0000ff", "name": "Blue"},
    "F3": {"range": "470-490nm", "color": "#00ffff", "name": "Cyan"},
    "F4": {"range": "505-525nm", "color": "#00ff00", "name": "Green"},
    "F5": {"range": "545-565nm", "color": "#aaff00", "name": "Yellow-Green"},
    "F6": {"range": "580-600nm", "color": "#ffff00", "name": "Yellow"},
    "F7": {"range": "620-640nm", "color": "#ff6600", "name": "Orange"},
    "F8": {"range": "670-690nm", "color": "#ff0000", "name": "Red"}
}
CHANNELS = list(CHANNEL_CONFIG.keys())

# ---------------------- 2. Filtering parameters ----------------------
WINDOW_SIZE = 5          # 滑动中位数窗口（奇数最佳）
JUMP_THRESHOLD = 3.0     # 突变检测阈值倍数（基于MAD）
SECOND_SMOOTH = True     # 是否在绘图时对趋势做二次平滑（savgol / fallback）

# ---------------------- 3. Utility: folders ----------------------
def create_folders(root, subfolders):
    if not os.path.exists(root):
        os.makedirs(root)
    folder_paths = {}
    for name in subfolders:
        p = os.path.join(root, name)
        if not os.path.exists(p):
            os.makedirs(p)
        folder_paths[name] = p
    return folder_paths

# ---------------------- 4. Time-series spike removal ----------------------
def time_series_spike_filter(series, window_size=WINDOW_SIZE, jump_threshold=JUMP_THRESHOLD):
    """
    对一维 pd.Series 做局部中位数替换突变（返回与输入 index 对齐的 pd.Series）
    逻辑：
      1) 计算滑动中值 med
      2) 计算 abs(series - med)，基于 MAD 定阈值
      3) 将超阈的点用中值替换
    """
    s = series.astype(float).copy()
    if len(s) == 0:
        return s

    # rolling median (centered)
    med = s.rolling(window=window_size, center=True, min_periods=1).median()

    # difference and MAD (基于局部差异)
    diff = (s - med).abs().fillna(0.0).values
    mad = np.median(diff)
    if mad == 0 or np.isnan(mad):
        mad = np.mean(diff) if np.mean(diff) > 0 else 1e-6

    threshold = jump_threshold * 1.4826 * mad  # approximate std from MAD

    s_filtered = s.copy()
    spike_mask = diff > threshold
    if np.any(spike_mask):
        s_filtered.iloc[spike_mask] = med.iloc[spike_mask]

    return s_filtered

# ---------------------- 5. Load & preprocess ----------------------
def load_and_preprocess_data(data_path):
    # load
    if data_path.endswith((".xlsx", ".xls")):
        df = pd.read_excel(data_path)
    elif data_path.endswith(".csv"):
        # try common encodings, fallback to default
        try:
            df = pd.read_csv(data_path, encoding="utf-8")
        except Exception:
            df = pd.read_csv(data_path, encoding="gbk", errors="replace")
    else:
        raise ValueError("Only CSV/XLSX supported.")

    required_cols = ["measurement_index", "measurement_time", "measurement_type", "data_index"] + CHANNELS
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    # drop rows where all channels are zero (噪声/无测量)
    df["total_channels"] = df[CHANNELS].sum(axis=1)
    df_valid = df[df["total_channels"] > 0].copy()
    df_valid = df_valid.drop(columns=["total_channels"])
    print(f"Loaded {len(df)} rows, {len(df_valid)} rows after removing all-zero rows.")

    # ensure time col is datetime
    df_valid["measurement_time"] = pd.to_datetime(df_valid["measurement_time"], errors="coerce")
    df_valid = df_valid.dropna(subset=["measurement_time"])
    print(f"{len(df_valid)} rows after dropping invalid times.")

    processed = {}
    for cond in CONDITION_FOLDERS:
        cond_df = df_valid[df_valid["measurement_type"] == cond].copy()
        if cond_df.empty:
            print(f"Warning: no data for condition '{cond}'.")
            processed[cond] = None
            continue

        # Group by measurement_time -> 对同一时间点取中位（抵抗离群）
        grouped = cond_df.groupby("measurement_time")[CHANNELS].median().reset_index().sort_values("measurement_time")
        # set index order
        grouped = grouped.reset_index(drop=True)

        # Apply time-series filter to each channel
        for ch in CHANNELS:
            grouped[ch] = time_series_spike_filter(grouped[ch], window_size=WINDOW_SIZE, jump_threshold=JUMP_THRESHOLD)

        processed[cond] = grouped
        print(f"Processed condition '{cond}': {len(grouped)} time points.")

    return processed

# ---------------------- 6. Plotting helpers ----------------------
def compute_ylim_with_margin(y, margin_ratio=0.10, min_margin=5.0):
    if np.all(np.isnan(y)):
        return (0, 1)
    ymin = np.nanmin(y)
    ymax = np.nanmax(y)
    if np.isclose(ymin, ymax):
        # constant series
        return (ymin - min_margin, ymax + min_margin)
    margin = max((ymax - ymin) * margin_ratio, min_margin)
    return (max(ymin - margin, 0), ymax + margin)

def smooth_for_plot(y):
    """
    返回用于绘图的更密集的平滑曲线 (x_smooth, y_smooth)
    优先使用 SciPy 的 savgol + cubic spline，如果不可用退化到简单移动平均 + np.interp
    """
    x = np.arange(len(y))
    # fallback: if very short series, return original
    if len(y) < 3:
        return x, y

    # first pass smoothing (reduce remaining small noise)
    if SCIPY_AVAILABLE and SECOND_SMOOTH:
        # savgol needs odd window <= len(y)
        window = min(51, len(y) if len(y) % 2 == 1 else len(y) - 1)
        window = max(3, window)  # at least 3
        try:
            y_sg = savgol_filter(y, window_length=window, polyorder=2, mode='interp')
        except Exception:
            y_sg = pd.Series(y).rolling(window=3, center=True, min_periods=1).mean().values
    else:
        # simple moving average fallback
        kernel = np.ones(3) / 3.0
        y_sg = np.convolve(y, kernel, mode='same')

    # upsample and spline/interp
    x_smooth = np.linspace(0, len(y) - 1, max(200, len(y) * 10))
    if SCIPY_AVAILABLE and len(y) >= 4:
        try:
            spline = make_interp_spline(x, y_sg, k=3)
            y_smooth = spline(x_smooth)
            return x_smooth, y_smooth
        except Exception:
            pass

    # fallback: linear interpolation
    y_smooth = np.interp(x_smooth, x, y_sg)
    return x_smooth, y_smooth

# ---------------------- 7. Plot single channel ----------------------
def plot_single_channel(cond, channel, data, save_path):
    cfg = CHANNEL_CONFIG[channel]
    y = data[channel].values
    times = data["measurement_time"]
    x = np.arange(len(y))
    time_labels = times.dt.strftime("%H:%M:%S").values

    fig, ax = plt.subplots(figsize=(max(10, len(y) * 0.6), 6))

    # Draw points (居中于 x ticks)
    ax.plot(x, y, marker='o', linestyle='-', linewidth=1.6,
            markersize=7, markeredgewidth=0.9, label=f"{channel} ({cfg['range']})",
            color=cfg["color"], alpha=0.95)

    # Smooth trend (dense curve)
    x_s, y_s = smooth_for_plot(y)
    ax.plot(x_s, y_s, linestyle='--', linewidth=2.8, alpha=0.6, label="Smoothed trend", color=cfg["color"])

    # labels & xticks
    ax.set_title(f"{cond} - {channel} ({cfg['range']}, {cfg['name']})", fontsize=14)
    ax.set_xlabel("Measurement Time")
    ax.set_ylabel("Mean Value")
    ax.grid(alpha=0.3)

    # X ticks: show at every point but rotate; if too crowded show fewer
    max_labels = 12
    if len(x) <= max_labels:
        tick_idx = x
        tick_labels = time_labels
    else:
        step = max(1, len(x) // max_labels)
        tick_idx = x[::step]
        tick_labels = time_labels[::step]
    ax.set_xticks(tick_idx)
    ax.set_xticklabels(tick_labels, rotation=45, ha='right', fontsize=9)

    # Y limit with margin
    ymin, ymax = compute_ylim_with_margin(y, margin_ratio=0.12, min_margin=5.0)
    ax.set_ylim(ymin, ymax)

    ax.legend(fontsize=9)
    plt.tight_layout()
    plt.savefig(save_path, dpi=300)
    plt.close()
    print(f"Saved: {save_path}")

# ---------------------- 8. Vertical comparison (8-subplots) ----------------------
def plot_vertical_comparison(cond, data, save_path):
    n = len(CHANNELS)
    fig, axes = plt.subplots(n, 1, figsize=(12, 30), sharex=True)
    fig.suptitle(f"{cond} Spectral Band Comparison", fontsize=16, y=0.99)

    x = np.arange(len(data))
    times = data["measurement_time"].dt.strftime("%H:%M:%S").values

    # decide xtick reduction
    max_labels = 12
    if len(x) <= max_labels:
        tick_idx = x
        tick_labels = times
    else:
        step = max(1, len(x) // max_labels)
        tick_idx = x[::step]
        tick_labels = times[::step]

    for i, ch in enumerate(CHANNELS):
        ax = axes[i]
        cfg = CHANNEL_CONFIG[ch]
        y = data[ch].values

        ax.plot(x, y, marker='o', markersize=5, linewidth=1.4,
                color=cfg['color'], label=f"{ch}: {cfg['range']} ({cfg['name']})", alpha=0.9)
        # smooth
        x_s, y_s = smooth_for_plot(y)
        ax.plot(x_s, y_s, linestyle='--', linewidth=2.2, color=cfg['color'], alpha=0.6)

        ax.set_ylabel("Mean Value", fontsize=10)
        ax.legend(loc="upper right", fontsize=9)
        ax.grid(alpha=0.25)
        ymin, ymax = compute_ylim_with_margin(y, margin_ratio=0.12, min_margin=5.0)
        ax.set_ylim(ymin, ymax)

        if i < n - 1:
            ax.set_xticks([])
        else:
            ax.set_xticks(tick_idx)
            ax.set_xticklabels(tick_labels, rotation=45, ha='right', fontsize=9)

    plt.subplots_adjust(top=0.97, hspace=0.3)
    plt.savefig(save_path, dpi=300)
    plt.close()
    print(f"Saved: {save_path}")

# ---------------------- 9. Main: process & plot ----------------------
def main():
    print("Scipy available for smoothing?" , SCIPY_AVAILABLE)
    folder_paths = create_folders(ROOT_FOLDER, CONDITION_FOLDERS)
    processed = load_and_preprocess_data(DATA_PATH)

    for cond in CONDITION_FOLDERS:
        df_cond = processed.get(cond)
        if df_cond is None:
            continue
        out_dir = folder_paths[cond]
        print(f"Generating plots for '{cond}' ({len(df_cond)} points)...")

        # single channel plots
        for ch in CHANNELS:
            out_file = os.path.join(out_dir, f"{cond.replace(' ', '_')}_{ch}_{CHANNEL_CONFIG[ch]['range']}.png")
            plot_single_channel(cond, ch, df_cond, out_file)

        # vertical comparison
        out_file2 = os.path.join(out_dir, f"{cond.replace(' ', '_')}_spectral_band_comparison.png")
        plot_vertical_comparison(cond, df_cond, out_file2)

    print("All done!")

if __name__ == "__main__":
    # Silence some matplotlib warnings in headless environments
    warnings.filterwarnings("ignore", category=UserWarning)
    main()
