import sys
from os import listdir, path
import subprocess
import numpy as np
import cv2
import pickle
import os
import json
from tqdm import tqdm

SHOW_PREPROCESS_PROGRESS = False
_pose_model = None
_face_alignment = None
_mediapipe_face_mesh = None


def _bbox_range_message(frame_count, average_range_minus, average_range_plus, upperbondrange):
    if not average_range_minus or not average_range_plus:
        return f"Total frames: {frame_count} No valid face landmarks detected, current value: {upperbondrange}"
    return (
        f"Total frames: {frame_count} Manually adjust range: "
        f"[ -{int(sum(average_range_minus) / len(average_range_minus))}"
        f"~{int(sum(average_range_plus) / len(average_range_plus))} ], "
        f"current value: {upperbondrange}"
    )


def _mmpose_runtime():
    global _pose_model, _face_alignment
    from mmpose.apis import inference_topdown, init_model
    from mmpose.structures import merge_data_samples
    if _pose_model is None or _face_alignment is None:
        import torch
        from face_detection import FaceAlignment, LandmarksType

        # initialize the mmpose model
        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        config_file = './musetalk/utils/dwpose/rtmpose-l_8xb32-270e_coco-ubody-wholebody-384x288.py'
        checkpoint_file = './models/dwpose/dw-ll_ucoco_384.pth'
        _pose_model = init_model(config_file, checkpoint_file, device=device)

        # initialize the face detection model
        fa_device = "cuda" if torch.cuda.is_available() else "cpu"
        _face_alignment = FaceAlignment(LandmarksType._2D, flip_input=False, device=fa_device)
    return {
        "backend": "mmpose",
        "model": _pose_model,
        "face_alignment": _face_alignment,
        "inference_topdown": inference_topdown,
        "merge_data_samples": merge_data_samples,
    }


def _mediapipe_runtime(import_error):
    global _mediapipe_face_mesh
    try:
        import mediapipe as mp
    except ImportError as exc:
        raise RuntimeError(
            "MuseTalk avatar preprocessing could not load OpenMMLab/mmcv and "
            "MediaPipe is not installed. The prepared-avatar runtime does not need "
            "either backend, but creating new avatar preprocess data or first-frame "
            "debug masks does. For CUDA 12.8 / RTX 50-series installs, install "
            "mediapipe or use an already-prepared avatar pack."
        ) from import_error
    if _mediapipe_face_mesh is None:
        _mediapipe_face_mesh = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=True,
            max_num_faces=1,
            refine_landmarks=True,
        )
    return {"backend": "mediapipe", "face_mesh": _mediapipe_face_mesh}


def _pose_runtime():
    try:
        return _mmpose_runtime()
    except Exception as exc:
        print(f"[MuseTalk] OpenMMLab preprocessing backend unavailable; using MediaPipe fallback ({exc})")
        return _mediapipe_runtime(exc)


def _mmpose_face_geometry(frame, runtime):
    results = runtime["inference_topdown"](runtime["model"], frame)
    results = runtime["merge_data_samples"](results)
    keypoints = results.pred_instances.keypoints
    face_land_mark = keypoints[0][23:91].astype(np.int32)
    bbox = runtime["face_alignment"].get_detections_for_batch(np.asarray([frame]))[0]
    if bbox is None:
        return None, None
    return {
        "all": face_land_mark,
        "nose_top": face_land_mark[28],
        "nose_mid": face_land_mark[29],
        "nose_lower": face_land_mark[30],
    }, bbox


def _mediapipe_face_geometry(frame, runtime):
    if frame is None:
        return None, None
    height, width = frame.shape[:2]
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    result = runtime["face_mesh"].process(rgb)
    if not result.multi_face_landmarks:
        return None, None
    landmarks = result.multi_face_landmarks[0].landmark
    points = np.asarray([[lm.x * width, lm.y * height] for lm in landmarks], dtype=np.float32)
    if len(points) <= 197:
        return None, None
    min_xy = np.floor(points.min(axis=0)).astype(np.int32)
    max_xy = np.ceil(points.max(axis=0)).astype(np.int32)
    x1 = int(np.clip(min_xy[0], 0, max(0, width - 1)))
    y1 = int(np.clip(min_xy[1], 0, max(0, height - 1)))
    x2 = int(np.clip(max_xy[0], x1 + 1, width))
    y2 = int(np.clip(max_xy[1], y1 + 1, height))
    return {
        "all": points,
        "nose_top": points[6],
        "nose_mid": points[197],
        "nose_lower": points[195],
    }, (x1, y1, x2, y2)


def _face_geometry(frame, runtime):
    if runtime.get("backend") == "mediapipe":
        return _mediapipe_face_geometry(frame, runtime)
    return _mmpose_face_geometry(frame, runtime)


def _face_coord_from_geometry(face_points, bbox, upperbondrange, average_range_minus, average_range_plus):
    if face_points is None or bbox is None:
        return coord_placeholder

    all_points = np.asarray(face_points["all"], dtype=np.float32)
    half_face_coord = np.asarray(face_points["nose_mid"], dtype=np.float32).copy()
    nose_top = np.asarray(face_points["nose_top"], dtype=np.float32)
    nose_lower = np.asarray(face_points["nose_lower"], dtype=np.float32)
    range_minus = float(nose_lower[1] - half_face_coord[1])
    range_plus = float(half_face_coord[1] - nose_top[1])
    average_range_minus.append(range_minus)
    average_range_plus.append(range_plus)
    if upperbondrange != 0:
        half_face_coord[1] = upperbondrange + half_face_coord[1] #手动调整  + 向下（偏29）  - 向上（偏28）

    min_x = int(np.min(all_points[:, 0]))
    max_x = int(np.max(all_points[:, 0]))
    max_y = int(np.max(all_points[:, 1]))
    half_face_dist = max_y - half_face_coord[1]
    min_upper_bond = 0
    upper_bond = max(min_upper_bond, half_face_coord[1] - half_face_dist)
    f_landmark = (min_x, int(upper_bond), max_x, max_y)
    x1, y1, x2, y2 = f_landmark

    if y2 - y1 <= 0 or x2 - x1 <= 0 or x1 < 0:
        w,h = bbox[2]-bbox[0], bbox[3]-bbox[1]
        print("error bbox:",bbox)
        return bbox
    return f_landmark

# maker if the bbox is not sufficient 
coord_placeholder = (0.0,0.0,0.0,0.0)

def resize_landmark(landmark, w, h, new_w, new_h):
    w_ratio = new_w / w
    h_ratio = new_h / h
    landmark_norm = landmark / [w, h]
    landmark_resized = landmark_norm * [new_w, new_h]
    return landmark_resized

def read_imgs(img_list):
    frames = []
    for img_path in tqdm(img_list, disable=not SHOW_PREPROCESS_PROGRESS):
        frame = cv2.imread(img_path)
        frames.append(frame)
    return frames

def get_bbox_range(img_list,upperbondrange =0):
    runtime = _pose_runtime()
    frames = read_imgs(img_list)
    batch_size_fa = 1
    batches = [frames[i:i + batch_size_fa] for i in range(0, len(frames), batch_size_fa)]
    coords_list = []
    landmarks = []
    if upperbondrange != 0:
        print('get key_landmark and face bounding boxes with the bbox_shift:',upperbondrange)
    else:
        print('get key_landmark and face bounding boxes with the default value')
    average_range_minus = []
    average_range_plus = []
    for fb in tqdm(batches, disable=not SHOW_PREPROCESS_PROGRESS):
        face_points, bbox = _face_geometry(np.asarray(fb)[0], runtime)
        coords_list += [_face_coord_from_geometry(face_points, bbox, upperbondrange, average_range_minus, average_range_plus)]

    text_range = _bbox_range_message(len(frames), average_range_minus, average_range_plus, upperbondrange)
    return text_range
    

def get_landmark_and_bbox(img_list,upperbondrange =0):
    runtime = _pose_runtime()
    frames = read_imgs(img_list)
    batch_size_fa = 1
    batches = [frames[i:i + batch_size_fa] for i in range(0, len(frames), batch_size_fa)]
    coords_list = []
    landmarks = []
    if upperbondrange != 0:
        print('get key_landmark and face bounding boxes with the bbox_shift:',upperbondrange)
    else:
        print('get key_landmark and face bounding boxes with the default value')
    average_range_minus = []
    average_range_plus = []
    for fb in tqdm(batches, disable=not SHOW_PREPROCESS_PROGRESS):
        face_points, bbox = _face_geometry(np.asarray(fb)[0], runtime)
        coords_list += [_face_coord_from_geometry(face_points, bbox, upperbondrange, average_range_minus, average_range_plus)]
    
    print("********************************************bbox_shift parameter adjustment**********************************************************")
    print(_bbox_range_message(len(frames), average_range_minus, average_range_plus, upperbondrange))
    print("*************************************************************************************************************************************")
    return coords_list,frames
    

if __name__ == "__main__":
    img_list = ["./results/lyria/00000.png","./results/lyria/00001.png","./results/lyria/00002.png","./results/lyria/00003.png"]
    crop_coord_path = "./coord_face.pkl"
    coords_list,full_frames = get_landmark_and_bbox(img_list)
    with open(crop_coord_path, 'wb') as f:
        pickle.dump(coords_list, f)
        
    for bbox, frame in zip(coords_list,full_frames):
        if bbox == coord_placeholder:
            continue
        x1, y1, x2, y2 = bbox
        crop_frame = frame[y1:y2, x1:x2]
        print('Cropped shape', crop_frame.shape)
        
        #cv2.imwrite(path.join(save_dir, '{}.png'.format(i)),full_frames[i][0][y1:y2, x1:x2])
    print(coords_list)
