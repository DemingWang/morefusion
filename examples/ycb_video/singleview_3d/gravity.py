#!/usr/bin/env python

import glooey
import imgviz
import numpy as np
import pybullet
import pyglet
import tqdm
import trimesh
import trimesh.viewer
import trimesh.transformations as tf

import objslampp

from common import Inference


models = objslampp.datasets.YCBVideoModels()

inference = Inference(gpu=0)
frame, T_cad2cam_true, T_cad2cam_pred = inference(index=0, bg_class=True)
keep = frame['class_ids'] > 0
class_ids_fg = frame['class_ids'][keep]

T_cad2world_pred = frame['T_cam2world'] @ T_cad2cam_pred
T_cad2world_true = frame['T_cam2world'] @ T_cad2cam_true

# -----------------------------------------------------------------------------

window = pyglet.window.Window(width=640 * 2, height=480 * 2)


@window.event
def on_key_press(symbol, modifiers):
    if modifiers == 0:
        if symbol == pyglet.window.key.Q:
            window.on_close()


gui = glooey.Gui(window)
grid = glooey.Grid(num_rows=2, num_cols=2)
grid.set_padding(5)

K = frame['intrinsic_matrix']
height, width = frame['rgb'].shape[:2]
T_cam2world = frame['T_cam2world']
T_world2cam = np.linalg.inv(T_cam2world)

# -----------------------------------------------------------------------------
# rgb

image = objslampp.extra.pyglet.numpy_to_image(frame['rgb'])
widget = glooey.Image(image, responsive=True)
vbox = glooey.VBox()
vbox.add(glooey.Label(text='input rgb', color=(255, 255, 255)), size=0)
vbox.add(widget)
grid[0, 0] = vbox

# -----------------------------------------------------------------------------
# depth

scene = trimesh.Scene()

depth = frame['depth']
pcd = objslampp.geometry.pointcloud_from_depth(
    depth, fx=K[0, 0], fy=K[1, 1], cx=K[0, 2], cy=K[1, 2]
)
nonnan = ~np.isnan(depth)
# depth_viz = imgviz.depth2rgb(frame['depth'])
colormap = imgviz.label_colormap(value=200)
label_viz = imgviz.label2rgb(frame['instance_label'], colormap=colormap)
geom = trimesh.PointCloud(
    vertices=pcd[nonnan],
    colors=label_viz[nonnan],
)
scene.add_geometry(geom, transform=T_cam2world)

# -----------------------------------------------------------------------------
# cad

for i in range(T_cad2world_pred.shape[0]):
    class_id = class_ids_fg[i]
    cad_file = models.get_cad_model(class_id=class_id)
    cad = trimesh.load(str(cad_file))
    cad.visual = cad.visual.to_color()
    # scene.add_geometry(cad, transform=T_cad2world_true[i])
    scene.add_geometry(cad, transform=T_cad2world_pred[i])

scene.camera.resolution = (width, height)
scene.camera.focal = (K[0, 0], K[1, 1])
scene.camera.transform = objslampp.extra.trimesh.camera_transform(T_cam2world)

widget = trimesh.viewer.SceneWidget(scene)
vbox = glooey.VBox()
vbox.add(glooey.Label(text='pcd & pred poses', color=(255, 255, 255)), size=0)
vbox.add(widget)
grid[0, 1] = vbox

# -----------------------------------------------------------------------------
# pybullet

objslampp.extra.pybullet.init_world(connection_method=pybullet.DIRECT)
# pybullet.resetDebugVisualizerCamera(
#     cameraDistance=0.8,
#     cameraYaw=30,
#     cameraPitch=-60,
#     cameraTargetPosition=(0, 0, 0),
# )

for ins_id, cad_file in frame['cad_files'].items():
    index = np.where(frame['instance_ids'] == ins_id)[0][0]
    T_cad2cam = frame['Ts_cad2cam'][index]
    T = frame['T_cam2world'] @ T_cad2cam
    objslampp.extra.pybullet.add_model(
        visual_file=cad_file,
        collision_file=objslampp.utils.get_collision_file(cad_file),
        position=tf.translation_from_matrix(T),
        orientation=tf.quaternion_from_matrix(T)[[1, 2, 3, 0]],
    )

for i in range(T_cad2world_pred.shape[0]):
    class_id = class_ids_fg[i]
    visual_file = models.get_cad_model(class_id=class_id)
    collision_file = objslampp.utils.get_collision_file(visual_file)
    T = T_cad2world_pred[i]
    # T = T_cad2world_true[i]
    objslampp.extra.pybullet.add_model(
        visual_file=visual_file,
        collision_file=collision_file,
        position=tf.translation_from_matrix(T),
        orientation=tf.quaternion_from_matrix(T)[[1, 2, 3, 0]],
    )

rgbs_sim = []
for _ in tqdm.tqdm(range(60)):
    rgb, _, _ = objslampp.extra.pybullet.render_camera(
        T_cam2world, fovy=scene.camera.fov[1], height=height, width=width
    )
    rgbs_sim.append(rgb)
    pybullet.stepSimulation()

pybullet.disconnect()


image = objslampp.extra.pyglet.numpy_to_image(rgbs_sim[0])
widget = glooey.Image(image, responsive=True)
vbox = glooey.VBox()
vbox.add(glooey.Label(text='pred rendered', color=(255, 255, 255)), size=0)
vbox.add(widget)
grid[1, 0] = vbox


def callback(dt, image_widget):
    if image_widget.index >= len(rgbs_sim):
        image_widget.index = 0
    rgb = rgbs_sim[image_widget.index]
    image_widget.index += 1
    image = objslampp.extra.pyglet.numpy_to_image(rgb)
    image_widget.set_image(image)


image_widget = glooey.Image(responsive=True)
image_widget.index = 0
pyglet.clock.schedule_interval(callback, 1 / 30, image_widget)
vbox = glooey.VBox()
vbox.add(
    glooey.Label(text='pred poses then gravity', color=(255, 255, 255)),
    size=0,
)
vbox.add(image_widget)
grid[1, 1] = vbox

# -----------------------------------------------------------------------------

gui.add(grid)
pyglet.app.run()