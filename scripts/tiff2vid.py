from PIL import Image
import glob
import os
import fire
import ffmpeg

def main(folder: str, recurse: bool = False):
    # if recurse, get list of all subfolders
    if recurse:
        folders = [x[0] for x in os.walk(folder)]
    else:
        folders = [folder]
    
    # loop over folders
    for folder in folders:
        # get list of all tiff files in folder
        tiff_files = glob.glob(os.path.join(folder, '*.tiff'))

        # get output video file name
        vid_name = os.path.basename(os.path.dirname(folder))
        vid_file = os.path.join('/home/buchsbaum/Videos/', vid_name + '.mp4')

        # create video
        (
            ffmpeg
            .input(os.path.join(folder, '*.tiff'), pattern_type='glob', framerate=25)
            .output(vid_file, rgb_mode='yuv420', vcodec='h264_nvenc', preset="p1")
            .run()
        )

if __name__ == '__main__':
    #fire.Fire(main)
    #main(folder="/home/buchsbaum/nfc3008/Videos/20240408_114853/322804_1823/", recurse=False)