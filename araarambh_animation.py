from manim import *
import numpy as np

class SphereVibration3D(ThreeDScene):
    def construct(self):
        # --- 1. SCENE SETUP ---
        # Use a ValueTracker for rotation
        theta_tracker = ValueTracker(-45 * DEGREES)

        self.set_camera_orientation(
            phi=75 * DEGREES,
            theta=theta_tracker.get_value(),
            zoom=0.8
        )

        # Update camera every frame to create smooth rotation
        self.add_updater(lambda: self.set_camera_orientation(
            phi=75 * DEGREES,
            theta=theta_tracker.get_value()
        ))

        self.camera.background_color = "#0f0f15"

        # --- 2. DEFINE THE WAVE FUNCTION ---
        def vibrating_geometry(u, v, t):
            R = 2.5
            x = R * np.cos(u) * np.cos(v)
            y = R * np.cos(u) * np.sin(v)
            z = R * np.sin(u)
            r_vec = np.array([x, y, z])
            norm = np.linalg.norm(r_vec)
            direction = r_vec / norm

            # Vibration modes
            w1 = 0.25 * np.sin(4 * u) * np.cos(2 * t)
            w2 = 0.15 * np.cos(u) * np.sin(3 * v - 1.5 * t)
            w3 = 0.1 * np.sin(6 * v + t) * np.sin(2 * u)
            total_amp = w1 + w2 + w3

            return direction * (R + total_amp)

        # --- 3. CREATE OBJECTS ---
        core = Sphere(
            radius=2.0,
            resolution=(30, 30),
            fill_opacity=1,
            stroke_width=0,
            color="#002b5c"
        )

        core_wireframe = Sphere(
            radius=2.01,
            resolution=(20, 20),
            stroke_color=GOLD,
            stroke_width=2,
            fill_opacity=0,
        )

        # Initialize surface at t=0
        wave_shell = Surface(
            lambda u, v: vibrating_geometry(u, v, 0),
            resolution=(40, 40), # Slightly reduced for performance
            u_range=[-PI / 2, PI / 2],
            v_range=[0, TAU],
            fill_opacity=0.7,
            stroke_color=WHITE,
            stroke_width=0.5,
            stroke_opacity=0.4,
            checkerboard_colors=["#8b0000", "#ff4500"]
        )

        # --- 4. ANIMATION SEQUENCE ---
        self.play(FadeIn(core), FadeIn(core_wireframe), run_time=1.5)
        self.wait(0.5)
        self.play(FadeIn(wave_shell))
        self.wait(1)

        # We define a function to update the surface based on elapsed time        
        def update_wave(m, dt):
            # self.time is not always reliable in all Manim versions,
            # using a manual timer or the current scene time
            t = self.time
            m.become(
                Surface(
                    lambda u, v: vibrating_geometry(u, v, t),
                    resolution=(40, 40),
                    u_range=[-PI / 2, PI / 2],
                    v_range=[0, TAU],
                    fill_opacity=0.7,
                    stroke_color=WHITE,
                    stroke_width=0.5,
                    stroke_opacity=0.4,
                    checkerboard_colors=["#8b0000", "#ff4500"]
                )
            )

        # Add the updater to the shell and start the rotation
        wave_shell.add_updater(update_wave)

        self.play(
            theta_tracker.animate.set_value(theta_tracker.get_value() + TAU),     
            run_time=10,
            rate_function=linear
        )

        # Remove updater before fading out to prevent errors
        wave_shell.remove_updater(update_wave)
        self.wait(0.5)
        self.play(FadeOut(Group(core, core_wireframe, wave_shell)))