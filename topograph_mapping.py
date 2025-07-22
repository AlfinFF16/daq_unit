import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import numpy as np
import plotly.graph_objs as go
import plotly.io as pio
import os
from datetime import datetime
from matplotlib import cm
from matplotlib.colors import Normalize

def parse_gga_latlon(gga_str):
    try:
        fields = gga_str.split(",")
        lat_raw = fields[2]
        lat_dir = fields[3]
        lon_raw = fields[4]
        lon_dir = fields[5]
        lat_deg = int(float(lat_raw) / 100)
        lat_min = float(lat_raw) - lat_deg * 100
        lat = lat_deg + lat_min / 60
        if lat_dir == 'S':
            lat *= -1
        lon_deg = int(float(lon_raw) / 100)
        lon_min = float(lon_raw) - lon_deg * 100
        lon = lon_deg + lon_min / 60
        if lon_dir == 'W':
            lon *= -1
        return lat, lon
    except:
        return None, None

def parse_depth(raw):
    """Extract depth in meters from DBT message"""
    try:
        # DBT format: $xxDBT,depth_feet,f,depth_meters,M,depth_fathoms,F
        parts = raw.split(',')
        # Find the 'M' field which indicates meters
        if 'M' in parts:
            idx = parts.index('M')
            if idx > 0:
                return float(parts[idx-1])
        # Fallback to try field 3 (depth in meters)
        return float(parts[3])
    except:
        return None

def parse_ins(raw):
    try:
        parts = raw.split(",")
        roll = float(parts[1])
        pitch = float(parts[2])
        heading = float(parts[3].split("*")[0])
        return roll, pitch, heading
    except:
        return None, None, None

def load_and_merge(u1, u2, u3):
    try:
        # Load CSV files with new format
        uart1 = pd.read_csv(u1)
        uart2 = pd.read_csv(u2)
        uart3 = pd.read_csv(u3)
        
        # Convert timestamps to datetime objects
        uart1["Device Timestamp"] = pd.to_datetime(uart1["Device Timestamp"], format='%H:%M:%S.%f')
        uart2["Device Timestamp"] = pd.to_datetime(uart2["Device Timestamp"], format='%H:%M:%S.%f')
        uart3["Device Timestamp"] = pd.to_datetime(uart3["Device Timestamp"], format='%H:%M:%S.%f')
        
        # Parse data from raw strings
        uart1[["lat", "lon"]] = uart1["Raw Data"].apply(lambda x: pd.Series(parse_gga_latlon(x)))
        uart2[["roll", "pitch", "heading"]] = uart2["Raw Data"].apply(lambda x: pd.Series(parse_ins(x)))
        uart3["depth_m"] = uart3["Raw Data"].apply(parse_depth)
        
        # Merge datasets based on timestamps
        df = pd.merge_asof(
            uart1.sort_values("Device Timestamp"),
            uart3.sort_values("Device Timestamp")[["Device Timestamp", "depth_m"]],
            on="Device Timestamp", direction="nearest", tolerance=pd.Timedelta("1s")
        )
        df = pd.merge_asof(
            df.sort_values("Device Timestamp"),
            uart2.sort_values("Device Timestamp")[["Device Timestamp", "roll", "pitch", "heading"]],
            on="Device Timestamp", direction="nearest", tolerance=pd.Timedelta("1s")
        )
        df = df.dropna(subset=["lat", "lon", "depth_m"])
        
        # Calculate local coordinates in meters
        mean_lat = df["lat"].mean()
        df["x"] = (df["lon"] - df["lon"].mean()) * 111320 * np.cos(np.radians(mean_lat))
        df["y"] = (df["lat"] - df["lat"].mean()) * 110540
        
        # Add timestamp for display
        df["Timestamp"] = df["Device Timestamp"].dt.strftime('%H:%M:%S.%f')
        
        return df
    except Exception as e:
        messagebox.showerror("Processing Error", f"Error loading or merging data: {str(e)}")
        return None

class HydrographicMapApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Hydrographic Mapping Tool")
        self.root.geometry("1200x800")
        self.root.minsize(1000, 700)
        self.setup_ui()
        self.df = None
        self.current_cmap = "viridis"
        
    def setup_ui(self):
        # Create main frames
        main_frame = tk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # File selection frame
        file_frame = tk.LabelFrame(main_frame, text="Data Input", padx=5, pady=5)
        file_frame.pack(fill=tk.X, padx=5, pady=5)
        
        # GPS Data
        tk.Label(file_frame, text="GPS Data (UART1):").grid(row=0, column=0, sticky='e', padx=5, pady=2)
        self.gps_entry = tk.Entry(file_frame, width=60)
        self.gps_entry.grid(row=0, column=1, padx=5, pady=2, sticky='ew')
        tk.Button(file_frame, text="Browse", command=lambda: self.browse_file(self.gps_entry)).grid(row=0, column=2, padx=5, pady=2)
        
        # INS Data
        tk.Label(file_frame, text="INS Data (UART2):").grid(row=1, column=0, sticky='e', padx=5, pady=2)
        self.ins_entry = tk.Entry(file_frame, width=60)
        self.ins_entry.grid(row=1, column=1, padx=5, pady=2, sticky='ew')
        tk.Button(file_frame, text="Browse", command=lambda: self.browse_file(self.ins_entry)).grid(row=1, column=2, padx=5, pady=2)
        
        # Depth Data
        tk.Label(file_frame, text="Depth Data (UART3):").grid(row=2, column=0, sticky='e', padx=5, pady=2)
        self.depth_entry = tk.Entry(file_frame, width=60)
        self.depth_entry.grid(row=2, column=1, padx=5, pady=2, sticky='ew')
        tk.Button(file_frame, text="Browse", command=lambda: self.browse_file(self.depth_entry)).grid(row=2, column=2, padx=5, pady=2)
        
        # Process button
        process_btn = tk.Button(file_frame, text="Process Data", command=self.process_data, 
                               bg="#4CAF50", fg="white", font=("Arial", 10, "bold"))
        process_btn.grid(row=3, column=1, pady=10, sticky='ew')
        
        # Depth estimation button
        self.depth_stats_btn = tk.Button(file_frame, text="Estimate Depth Stats", 
                                        command=self.show_depth_stats, state=tk.DISABLED,
                                        bg="#2196F3", fg="white")
        self.depth_stats_btn.grid(row=3, column=2, padx=5, pady=10, sticky='ew')
        
        # Configure grid weights
        file_frame.columnconfigure(1, weight=1)
        
        # Visualization controls
        control_frame = tk.LabelFrame(main_frame, text="Visualization Controls", padx=5, pady=5)
        control_frame.pack(fill=tk.X, padx=5, pady=5)
        
        # Colormap selection
        tk.Label(control_frame, text="Color Map:").grid(row=0, column=0, padx=5, pady=2, sticky='e')
        self.cmap_var = tk.StringVar(value="viridis")
        cmap_options = ["viridis", "plasma", "inferno", "magma", "cividis", "jet", "coolwarm", "rainbow"]
        cmap_dropdown = ttk.Combobox(control_frame, textvariable=self.cmap_var, values=cmap_options, width=15)
        cmap_dropdown.grid(row=0, column=1, padx=5, pady=2, sticky='w')
        cmap_dropdown.bind("<<ComboboxSelected>>", self.update_plot)
        
        # Point size control
        tk.Label(control_frame, text="Point Size:").grid(row=0, column=2, padx=5, pady=2, sticky='e')
        self.size_var = tk.IntVar(value=30)
        size_slider = tk.Scale(control_frame, from_=1, to=100, orient=tk.HORIZONTAL, 
                              variable=self.size_var, showvalue=True, length=150)
        size_slider.grid(row=0, column=3, padx=5, pady=2, sticky='w')
        size_slider.bind("<ButtonRelease-1>", self.update_plot)
        
        # Depth range
        tk.Label(control_frame, text="Depth Range:").grid(row=0, column=4, padx=5, pady=2, sticky='e')
        self.min_depth_var = tk.DoubleVar(value=0)
        self.max_depth_var = tk.DoubleVar(value=100)
        min_entry = tk.Entry(control_frame, textvariable=self.min_depth_var, width=6)
        min_entry.grid(row=0, column=5, padx=2, pady=2, sticky='w')
        tk.Label(control_frame, text="to").grid(row=0, column=6, padx=2, pady=2)
        max_entry = tk.Entry(control_frame, textvariable=self.max_depth_var, width=6)
        max_entry.grid(row=0, column=7, padx=2, pady=2, sticky='w')
        tk.Button(control_frame, text="Apply", command=self.update_plot).grid(row=0, column=8, padx=5, pady=2)
        
        # Stats display
        self.stats_var = tk.StringVar(value="No data processed")
        stats_label = tk.Label(control_frame, textvariable=self.stats_var, fg="blue")
        stats_label.grid(row=0, column=9, padx=10, pady=2, sticky='e')
        
        # Configure grid weights
        control_frame.columnconfigure(9, weight=1)
        
        # Plot frame
        plot_frame = tk.Frame(main_frame)
        plot_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        # Matplotlib figure and canvas
        self.fig, self.ax = plt.subplots(figsize=(8, 6))
        self.canvas = FigureCanvasTkAgg(self.fig, master=plot_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        # Add navigation toolbar
        self.toolbar = NavigationToolbar2Tk(self.canvas, plot_frame)
        self.toolbar.update()
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        
        # Export frame
        export_frame = tk.LabelFrame(main_frame, text="Export Options", padx=5, pady=5)
        export_frame.pack(fill=tk.X, padx=5, pady=5)
        
        # Export buttons
        tk.Button(export_frame, text="Export CSV", command=self.export_csv, 
                 width=15, bg="#2196F3", fg="white").pack(side=tk.LEFT, padx=5, pady=5)
        tk.Button(export_frame, text="Export GeoJSON", command=lambda: self.export_geo("geojson"), 
                 width=15, bg="#2196F3", fg="white").pack(side=tk.LEFT, padx=5, pady=5)
        tk.Button(export_frame, text="Export Shapefile", command=lambda: self.export_geo("shapefile"), 
                 width=15, bg="#2196F3", fg="white").pack(side=tk.LEFT, padx=5, pady=5)
        tk.Button(export_frame, text="Show 3D Plot", command=self.plot_3d_map, 
                 width=15, bg="#FF9800", fg="white").pack(side=tk.LEFT, padx=5, pady=5)
        tk.Button(export_frame, text="Save Plot as Image", command=self.save_plot_image, 
                 width=15, bg="#9C27B0", fg="white").pack(side=tk.LEFT, padx=5, pady=5)
    
    def browse_file(self, entry_widget):
        file_path = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv")])
        if file_path:
            entry_widget.delete(0, tk.END)
            entry_widget.insert(0, file_path)
    
    def process_data(self):
        gps_file = self.gps_entry.get()
        ins_file = self.ins_entry.get()
        depth_file = self.depth_entry.get()
        
        if not all([gps_file, ins_file, depth_file]):
            messagebox.showwarning("Input Error", "Please select all three data files")
            return
        
        # Show processing status
        self.stats_var.set("Processing data...")
        self.root.update()
        
        self.df = load_and_merge(gps_file, ins_file, depth_file)
        
        if self.df is not None:
            self.update_plot()
            self.update_stats()
            self.depth_stats_btn.config(state=tk.NORMAL)  # Enable depth stats button
    
    def update_plot(self, event=None):
        if self.df is None:
            return
            
        self.ax.clear()
        
        # Filter by depth range
        min_depth = self.min_depth_var.get()
        max_depth = self.max_depth_var.get()
        df_filtered = self.df[(self.df['depth_m'] >= min_depth) & (self.df['depth_m'] <= max_depth)]
        
        # Get colormap and point size
        cmap_name = self.cmap_var.get()
        point_size = self.size_var.get()
        
        # Create scatter plot
        sc = self.ax.scatter(
            df_filtered["x"], 
            df_filtered["y"], 
            c=df_filtered["depth_m"], 
            cmap=cmap_name, 
            s=point_size,
            edgecolor='none',
            alpha=0.8
        )
        
        # Add colorbar
        cbar = self.fig.colorbar(sc, ax=self.ax)
        cbar.set_label("Depth (m)")
        
        # Set labels and title
        self.ax.set_xlabel("Easting (m)")
        self.ax.set_ylabel("Northing (m)")
        self.ax.set_title("Hydrographic Depth Map")
        self.ax.grid(True, linestyle='--', alpha=0.7)
        
        # Update the canvas
        self.canvas.draw()
    
    def update_stats(self):
        if self.df is None:
            return
            
        min_depth = self.df['depth_m'].min()
        max_depth = self.df['depth_m'].max()
        avg_depth = self.df['depth_m'].mean()
        points_count = len(self.df)
        
        stats_text = (f"Points: {points_count:,} | "
                     f"Depth: Min={min_depth:.2f}m, Max={max_depth:.2f}m, Avg={avg_depth:.2f}m")
        self.stats_var.set(stats_text)
    
    def show_depth_stats(self):
        """Display detailed depth statistics in a messagebox"""
        if self.df is None:
            messagebox.showwarning("Depth Stats", "No data available")
            return
            
        # Calculate depth statistics
        depth_data = self.df['depth_m']
        min_depth = depth_data.min()
        max_depth = depth_data.max()
        avg_depth = depth_data.mean()
        std_depth = depth_data.std()
        median_depth = depth_data.median()
        
        # Create histogram for depth distribution
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.hist(depth_data, bins=50, color='#2196F3', edgecolor='white')
        ax.set_title('Depth Distribution')
        ax.set_xlabel('Depth (m)')
        ax.set_ylabel('Frequency')
        ax.grid(True, linestyle='--', alpha=0.7)
        
        # Save the histogram to a temporary file
        temp_file = "depth_histogram.png"
        fig.savefig(temp_file, dpi=100, bbox_inches='tight')
        plt.close(fig)
        
        # Create stats message
        stats_message = (
            f"Depth Statistics:\n\n"
            f"Min Depth: {min_depth:.2f} m\n"
            f"Max Depth: {max_depth:.2f} m\n"
            f"Average Depth: {avg_depth:.2f} m\n"
            f"Median Depth: {median_depth:.2f} m\n"
            f"Standard Deviation: {std_depth:.2f} m\n\n"
            f"Depth distribution shown in histogram."
        )
        
        # Create custom dialog to show stats and histogram
        stats_dialog = tk.Toplevel(self.root)
        stats_dialog.title("Depth Statistics")
        stats_dialog.geometry("600x500")
        
        # Stats text
        text_frame = tk.Frame(stats_dialog)
        text_frame.pack(padx=10, pady=10, fill=tk.X)
        tk.Label(text_frame, text=stats_message, justify=tk.LEFT).pack(anchor=tk.W)
        
        # Histogram image
        img = tk.PhotoImage(file=temp_file)
        img_label = tk.Label(stats_dialog, image=img)
        img_label.image = img  # Keep reference
        img_label.pack(padx=10, pady=10)
        
        # Close button
        tk.Button(stats_dialog, text="Close", command=stats_dialog.destroy).pack(pady=10)
        
        # Clean up temporary file
        os.remove(temp_file)
    
    def export_csv(self):
        if self.df is None:
            messagebox.showwarning("Export Error", "No data to export")
            return
            
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", 
            filetypes=[("CSV files", "*.csv")],
            initialfile=f"hydro_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        )
        if path:
            try:
                # Export only relevant columns
                export_df = self.df[['Timestamp', 'lat', 'lon', 'depth_m', 'roll', 'pitch', 'heading']]
                export_df.to_csv(path, index=False)
                messagebox.showinfo("Export Successful", f"CSV file saved to:\n{path}")
            except Exception as e:
                messagebox.showerror("Export Error", f"Failed to export CSV: {str(e)}")
    
    def export_geo(self, export_format):
        if self.df is None:
            messagebox.showwarning("Export Error", "No data to export")
            return
            
        # Create GeoDataFrame
        gdf = gpd.GeoDataFrame(
            self.df, 
            geometry=gpd.points_from_xy(self.df.lon, self.df.lat), 
            crs="EPSG:4326"
        )
        
        # Set file dialog options
        file_types = [("GeoJSON", "*.geojson")] if export_format == "geojson" else [("Shapefile", "*.shp")]
        ext = ".geojson" if export_format == "geojson" else ".shp"
        default_name = f"hydro_{export_format}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
        
        path = filedialog.asksaveasfilename(
            defaultextension=ext,
            filetypes=file_types,
            initialfile=default_name
        )
        
        if path:
            try:
                driver = "GeoJSON" if export_format == "geojson" else "ESRI Shapefile"
                gdf.to_file(path, driver=driver)
                messagebox.showinfo("Export Successful", f"{export_format.upper()} saved to:\n{path}")
            except Exception as e:
                messagebox.showerror("Export Error", f"Failed to export {export_format}: {str(e)}")
    
    def plot_3d_map(self):
        if self.df is None:
            messagebox.showwarning("3D Plot Error", "No data to plot")
            return
            
        # Create 3D scatter plot
        fig = go.Figure(data=[go.Scatter3d(
            x=self.df["x"],
            y=self.df["y"],
            z=-self.df["depth_m"],  # Negative depth to show below surface
            mode='markers',
            marker=dict(
                size=4,
                color=self.df["depth_m"],
                colorscale=self.cmap_var.get(),
                opacity=0.8,
                colorbar=dict(title='Depth (m)')
            )
        )])
        
        # Configure layout
        fig.update_layout(
            title="3D Hydrographic Map",
            scene=dict(
                xaxis_title='Easting (m)',
                yaxis_title='Northing (m)',
                zaxis_title='Depth (m)',
                aspectmode='data',
                camera=dict(eye=dict(x=1.5, y=1.5, z=0.8))
        ))
        
        # Show the plot
        pio.show(fig)
    
    def save_plot_image(self):
        if self.df is None:
            messagebox.showwarning("Save Error", "No plot to save")
            return
            
        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG Image", "*.png"), ("JPEG Image", "*.jpg"), ("PDF Document", "*.pdf")],
            initialfile=f"hydro_map_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        )
        if path:
            try:
                self.fig.savefig(path, dpi=300, bbox_inches='tight')
                messagebox.showinfo("Save Successful", f"Plot image saved to:\n{path}")
            except Exception as e:
                messagebox.showerror("Save Error", f"Failed to save image: {str(e)}")

if __name__ == "__main__":
    root = tk.Tk()
    app = HydrographicMapApp(root)
    root.mainloop()