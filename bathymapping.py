import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from scipy.interpolate import griddata
from mpl_toolkits.mplot3d import Axes3D

# --- Main Application Class ---
class HydrographicApp(tk.Tk):
    """
    An interactive GUI application for visualizing hydrographic data
    from a CSV file as a 2D depth map and a 3D surface plot, with map overlay capability.
    """
    def __init__(self):
        super().__init__()

        # --- Window Configuration ---
        self.title("Hydrographic Data Visualizer")
        self.geometry("1400x900")
        self.configure(bg="#2E2E2E")

        # --- Style Configuration ---
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure("TFrame", background="#2E2E2E")
        style.configure("TLabel", background="#2E2E2E", foreground="white", font=('Arial', 10))
        style.configure("TButton", background="#4A4A4A", foreground="white", font=('Arial', 10, 'bold'), borderwidth=0)
        style.map("TButton", background=[('active', '#6A6A6A')])
        style.configure("Header.TLabel", font=('Arial', 16, 'bold'))
        style.configure("TNotebook", background="#2E2E2E", borderwidth=0)
        style.configure("TNotebook.Tab", background="#4A4A4A", foreground="white", font=('Arial', 10, 'bold'), padding=[10, 5])
        style.map("TNotebook.Tab", background=[("selected", "#007ACC"), ('active', '#6A6A6A')])
        style.configure("TEntry", fieldbackground="#5A5A5A", foreground="white", borderwidth=0, insertbackground='white')
        style.configure("TCheckbutton", background="#2E2E2E", foreground="white")
        style.map("TCheckbutton", background=[('active', '#4A4A4A')])

        # --- Data Storage ---
        self.df = None
        self.points = None
        self.values = None
        self.map_image = None

        # --- UI Initialization ---
        self._create_widgets()

    def _create_widgets(self):
        """Creates and arranges all the UI components."""
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(expand=True, fill="both")

        controls_frame = ttk.Frame(main_frame, width=280, padding="10")
        controls_frame.pack(side="left", fill="y", padx=(0, 10))
        controls_frame.pack_propagate(False)

        plots_frame = ttk.Frame(main_frame)
        plots_frame.pack(side="left", expand=True, fill="both")

        # --- Controls Panel ---
        ttk.Label(controls_frame, text="Controls", style="Header.TLabel").pack(pady=(0, 15), anchor="w")

        # File Loading
        self.load_button = ttk.Button(controls_frame, text="Load CSV Data", command=self.load_csv)
        self.load_button.pack(fill="x", pady=5)
        self.file_label = ttk.Label(controls_frame, text="No data loaded.", wraplength=260)
        self.file_label.pack(fill="x", pady=5)
        
        ttk.Separator(controls_frame, orient='horizontal').pack(fill='x', pady=15)

        # Plotting Options
        ttk.Label(controls_frame, text="Plotting Options", font=('Arial', 12, 'bold')).pack(pady=(0, 10), anchor="w")
        # ... (existing plotting options) ...
        ttk.Label(controls_frame, text="Interpolation Method:").pack(anchor="w", pady=(5,0))
        self.interp_method = tk.StringVar(value='cubic')
        interp_menu = ttk.OptionMenu(controls_frame, self.interp_method, 'cubic', 'cubic', 'linear', 'nearest', command=lambda _: self.update_plots())
        interp_menu.pack(fill="x")

        ttk.Label(controls_frame, text="Grid Resolution:").pack(anchor="w", pady=(10,0))
        self.resolution = tk.IntVar(value=100)
        resolution_slider = ttk.Scale(controls_frame, from_=10, to=500, orient='horizontal', variable=self.resolution, command=lambda _: self.update_plots_on_drag())
        resolution_slider.pack(fill="x")
        
        ttk.Separator(controls_frame, orient='horizontal').pack(fill='x', pady=15)

        # Manual Depth Scale
        ttk.Label(controls_frame, text="Manual Depth Scale", font=('Arial', 12, 'bold')).pack(pady=(0, 10), anchor="w")
        self.use_manual_scale = tk.BooleanVar(value=False)
        manual_scale_check = ttk.Checkbutton(controls_frame, text="Use Manual Scale", variable=self.use_manual_scale, command=self.toggle_manual_scale)
        manual_scale_check.pack(anchor="w")
        # ... (existing depth scale entries) ...
        self.manual_scale_frame = ttk.Frame(controls_frame)
        self.manual_scale_frame.pack(fill='x', expand=True)
        ttk.Label(self.manual_scale_frame, text="Min Depth:").pack(anchor="w", pady=(5,0))
        self.min_depth_var = tk.StringVar()
        self.min_depth_entry = ttk.Entry(self.manual_scale_frame, textvariable=self.min_depth_var)
        self.min_depth_entry.pack(fill="x")
        ttk.Label(self.manual_scale_frame, text="Max Depth:").pack(anchor="w", pady=(5,0))
        self.max_depth_var = tk.StringVar()
        self.max_depth_entry = ttk.Entry(self.manual_scale_frame, textvariable=self.max_depth_var)
        self.max_depth_entry.pack(fill="x")
        self.min_depth_var.trace_add("write", lambda *args: self.update_plots_on_drag())
        self.max_depth_var.trace_add("write", lambda *args: self.update_plots_on_drag())
        
        ttk.Separator(controls_frame, orient='horizontal').pack(fill='x', pady=15)

        # --- NEW: Map Overlay Section ---
        ttk.Label(controls_frame, text="Map Overlay", font=('Arial', 12, 'bold')).pack(pady=(0, 10), anchor="w")
        self.load_map_button = ttk.Button(controls_frame, text="Load Map Image", command=self.load_map_image)
        self.load_map_button.pack(fill="x", pady=5)
        self.map_label = ttk.Label(controls_frame, text="No map loaded.", wraplength=260)
        self.map_label.pack(fill="x", pady=5)
        
        self.show_map_var = tk.BooleanVar(value=True)
        self.show_map_check = ttk.Checkbutton(controls_frame, text="Show Map Overlay", variable=self.show_map_var, command=self.update_plots)
        self.show_map_check.pack(anchor="w")

        ttk.Label(controls_frame, text="Map Transparency:").pack(anchor="w", pady=(10,0))
        self.map_alpha = tk.DoubleVar(value=0.7)
        map_alpha_slider = ttk.Scale(controls_frame, from_=0.0, to=1.0, orient='horizontal', variable=self.map_alpha, command=lambda _: self.update_plots_on_drag())
        map_alpha_slider.pack(fill="x")
        
        self.georeference_frame = ttk.Frame(controls_frame)
        # Georeference entries will be added here dynamically
        
        # --- Plotting Area ---
        self.notebook = ttk.Notebook(plots_frame)
        self.notebook.pack(expand=True, fill="both")
        self.tab2d = ttk.Frame(self.notebook)
        self.notebook.add(self.tab2d, text='2D Depth Map')
        self.fig2d = plt.figure(facecolor="#1E1E1E")
        self.canvas2d = FigureCanvasTkAgg(self.fig2d, master=self.tab2d)
        self.canvas2d.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=1)
        self.toolbar2d = NavigationToolbar2Tk(self.canvas2d, self.tab2d)
        self.toolbar2d.update()

        self.tab3d = ttk.Frame(self.notebook)
        self.notebook.add(self.tab3d, text='3D Surface')
        self.fig3d = plt.figure(facecolor="#1E1E1E")
        self.canvas3d = FigureCanvasTkAgg(self.fig3d, master=self.tab3d)
        self.canvas3d.get_tk_widget().pack(side=tk.TOP, fill=tk.BOTH, expand=1)
        
        self.toggle_manual_scale()

    def load_map_image(self):
        """Opens a file dialog to select a map image and prepares for georeferencing."""
        filepath = filedialog.askopenfilename(filetypes=[("Image Files", "*.png *.jpg *.jpeg *.tif *.tiff"), ("All files", "*.*")])
        if not filepath:
            return
        try:
            self.map_image = mpimg.imread(filepath)
            self.map_label.config(text=f"Loaded: {filepath.split('/')[-1]}")
            self.setup_georeference_controls()
            self.update_plots()
        except Exception as e:
            messagebox.showerror("Error Loading Image", f"Failed to load image file.\n\nError: {e}")
            self.map_image = None
            
    def setup_georeference_controls(self):
        """Creates or updates the georeferencing entry widgets."""
        # Clear existing widgets if any
        for widget in self.georeference_frame.winfo_children():
            widget.destroy()
            
        ttk.Label(self.georeference_frame, text="Georeference (Map Edges):", font=('Arial', 10, 'bold')).pack(anchor="w", pady=(10,0))
        
        # Create StringVars for the entries
        self.map_lon_min_var = tk.StringVar()
        self.map_lon_max_var = tk.StringVar()
        self.map_lat_min_var = tk.StringVar()
        self.map_lat_max_var = tk.StringVar()
        
        # If data is loaded, pre-populate with data extent as a good guess
        if self.df is not None and not self.df.empty:
            self.map_lon_min_var.set(f"{self.points[:, 0].min():.6f}")
            self.map_lon_max_var.set(f"{self.points[:, 0].max():.6f}")
            self.map_lat_min_var.set(f"{self.points[:, 1].min():.6f}")
            self.map_lat_max_var.set(f"{self.points[:, 1].max():.6f}")

        # Create the widgets
        ttk.Label(self.georeference_frame, text="Min Longitude (Left):").pack(anchor="w")
        ttk.Entry(self.georeference_frame, textvariable=self.map_lon_min_var).pack(fill="x")
        ttk.Label(self.georeference_frame, text="Max Longitude (Right):").pack(anchor="w")
        ttk.Entry(self.georeference_frame, textvariable=self.map_lon_max_var).pack(fill="x")
        ttk.Label(self.georeference_frame, text="Min Latitude (Bottom):").pack(anchor="w")
        ttk.Entry(self.georeference_frame, textvariable=self.map_lat_min_var).pack(fill="x")
        ttk.Label(self.georeference_frame, text="Max Latitude (Top):").pack(anchor="w")
        ttk.Entry(self.georeference_frame, textvariable=self.map_lat_max_var).pack(fill="x")
        
        # Update plot whenever a value is changed
        for var in [self.map_lon_min_var, self.map_lon_max_var, self.map_lat_min_var, self.map_lat_max_var]:
            var.trace_add("write", lambda *args: self.update_plots_on_drag())
            
        self.georeference_frame.pack(fill='x', expand=True, pady=(5,0))

    def update_plots(self):
        """Re-interpolates and redraws both the 2D and 3D plots."""
        if self.df is None or self.df.empty:
            self.show_placeholder_text()
            return

        try:
            # ... (Get manual scale values vmin, vmax) ...
            vmin, vmax = None, None
            if self.use_manual_scale.get():
                try:
                    vmin = float(self.min_depth_var.get())
                    vmax = float(self.max_depth_var.get())
                except (ValueError, TypeError): vmin, vmax = None, None

            res = complex(0, self.resolution.get())
            grid_x, grid_y = np.mgrid[
                self.points[:, 0].min():self.points[:, 0].max():res,
                self.points[:, 1].min():self.points[:, 1].max():res
            ]
            grid_z = griddata(self.points, self.values, (grid_x, grid_y), method=self.interp_method.get())

            # --- Update 2D Plot ---
            self.fig2d.clear()
            ax2d = self.fig2d.add_subplot(111)
            ax2d.set_facecolor("#1E1E1E")

            # --- Draw Map Overlay if available ---
            if self.map_image is not None and self.show_map_var.get():
                try:
                    extent = [
                        float(self.map_lon_min_var.get()), float(self.map_lon_max_var.get()),
                        float(self.map_lat_min_var.get()), float(self.map_lat_max_var.get())
                    ]
                    ax2d.imshow(self.map_image, extent=extent, aspect='auto', alpha=self.map_alpha.get())
                except (ValueError, TypeError, AttributeError):
                    pass # Ignore if georeference values are invalid/missing

            # Draw contour plot on top
            contour = ax2d.contourf(grid_x, grid_y, grid_z, levels=15, cmap='viridis_r', vmin=vmin, vmax=vmax, alpha=0.7)
            
            # ... (rest of 2D plotting logic) ...
            cbar2d = self.fig2d.colorbar(contour, ax=ax2d)
            cbar2d.set_label(f'Depth ({self.depth_col})', color='white')
            cbar2d.ax.yaxis.set_tick_params(color='white')
            plt.setp(plt.getp(cbar2d.ax.axes, 'yticklabels'), color='white')
            ax2d.scatter(self.points[:, 0], self.points[:, 1], c='red', s=15, edgecolors='black', label='Data Points')
            ax2d.set_xlabel(f'Longitude ({self.lon_col})', color='white')
            ax2d.set_ylabel(f'Latitude ({self.lat_col})', color='white')
            ax2d.set_title('2D Interpolated Depth Map', color='white', weight='bold')
            ax2d.legend(facecolor='#4A4A4A', labelcolor='white', edgecolor='none')
            ax2d.set_aspect('equal', adjustable='box')
            ax2d.tick_params(colors='white')
            self.canvas2d.draw()

            # --- Update 3D Plot ---
            self.fig3d.clear()
            ax3d = self.fig3d.add_subplot(111, projection='3d')
            ax3d.set_facecolor("#1E1E1E")
            ax3d.plot_surface(grid_x, grid_y, grid_z, cmap='viridis_r', edgecolor='none', antialiased=True, vmin=vmin, vmax=vmax)
            # ... (rest of 3D plotting logic) ...
            ax3d.set_xlabel(f'Longitude ({self.lon_col})', color='white')
            ax3d.set_ylabel(f'Latitude ({self.lat_col})', color='white')
            ax3d.set_zlabel(f'Depth ({self.depth_col})', color='white')
            ax3d.set_title('3D Surface Visualization', color='white', weight='bold')
            ax3d.tick_params(colors='white')
            if vmin is not None and vmax is not None:
                ax3d.set_zlim(vmax, vmin) 
            else:
                if ax3d.get_zlim()[1] > ax3d.get_zlim()[0]:
                     ax3d.invert_zaxis()
            self.canvas3d.draw()

        except Exception as e:
            if not self.use_manual_scale.get():
                messagebox.showerror("Plotting Error", f"An error occurred while generating plots.\n\nError: {e}")
                self.show_placeholder_text()

    # --- Other helper methods (load_csv, toggle_manual_scale, etc.) go here ---
    # (These methods are unchanged from the previous version)

    def toggle_manual_scale(self):
        state = "normal" if self.use_manual_scale.get() else "disabled"
        self.min_depth_entry.config(state=state)
        self.max_depth_entry.config(state=state)
        self.update_plots()

    def show_placeholder_text(self):
        self.fig2d.clear()
        ax2d = self.fig2d.add_subplot(111)
        ax2d.set_facecolor("#1E1E1E")
        ax2d.text(0.5, 0.5, "Load CSV data to begin", ha='center', va='center', fontsize=16, color='gray')
        ax2d.tick_params(axis='x', colors='none'); ax2d.tick_params(axis='y', colors='none')
        self.fig3d.clear()
        ax3d = self.fig3d.add_subplot(111, projection='3d')
        ax3d.set_facecolor("#1E1E1E")
        ax3d.text2D(0.5, 0.5, "Load CSV data to begin", ha='center', va='center', fontsize=16, color='gray', transform=ax3d.transAxes)
        self.canvas2d.draw(); self.canvas3d.draw()

    def load_csv(self):
        filepath = filedialog.askopenfilename(filetypes=[("CSV Files", "*.csv"), ("All files", "*.*")])
        if not filepath: return
        try:
            self.df = pd.read_csv(filepath)
            required_cols = {'lat': None, 'lon': None, 'depth': None}
            for col in self.df.columns:
                col_lower = col.lower()
                if 'lat' in col_lower: required_cols['lat'] = col
                elif 'lon' in col_lower: required_cols['lon'] = col
                elif 'depth' in col_lower or 'z' in col_lower: required_cols['depth'] = col
            if None in required_cols.values(): raise ValueError(f"CSV must contain 'lat', 'lon', and 'depth' columns. Found: {list(self.df.columns)}")
            self.lat_col, self.lon_col, self.depth_col = required_cols['lat'], required_cols['lon'], required_cols['depth']
            self.df = self.df[[self.lat_col, self.lon_col, self.depth_col]].dropna()
            self.points = self.df[[self.lon_col, self.lat_col]].values
            self.values = self.df[self.depth_col].values
            self.file_label.config(text=f"Loaded: {filepath.split('/')[-1]}")
            self.min_depth_var.set(f"{self.values.min():.2f}")
            self.max_depth_var.set(f"{self.values.max():.2f}")
            if self.map_image is not None: self.setup_georeference_controls()
            if self.use_manual_scale.get():
                self.use_manual_scale.set(False)
                self.toggle_manual_scale()
            else:
                self.update_plots()
        except Exception as e:
            messagebox.showerror("Error Loading File", f"Failed to load or process file.\n\nError: {e}")
            self.df = None; self.show_placeholder_text()

    def update_plots_on_drag(self):
        try: self.after_cancel(self._drag_job)
        except AttributeError: pass
        self._drag_job = self.after(250, self.update_plots)

# --- Application Entry Point ---
if __name__ == "__main__":
    app = HydrographicApp()
    app.mainloop()
