# Linux
Step 1: Install [Anaconda](https://www.anaconda.com/products/individual)
- Please follow the steps in this [blog](https://linuxize.com/post/how-to-install-anaconda-on-ubuntu-18-04/)

Step 2: Install OpenAI

- Open an ubuntu terminal and type:
   ```
   sudo apt-get update && sudo apt-get install cmake libopenmpi-dev python3-dev zlib1g-dev libgl1-mesa-glx swig
   ```
Step 3: Install [`Modernise-TradeMaster`](https://github.com/eewnah1/Modernise-TradeMaster)
- Open a terminal amd type 
  ```
  conda create --name Modernise-TradeMaster python=3.7.13
  ```
  to install a new conda environment for `Modernise-TradeMaster`
- Install `Modernise-TradeMaster`
  ```
  git clone https://github.com/eewnah1/Modernise-TradeMaster.git
  ```
- Open the folder `Modernise-TradeMaster` and open a terminal under the same position
- Install the dependency of `Modernise-TradeMaster`, run the command:
   ```
   conda activate Modernise-TradeMaster
   cd ./requirement
   pip install -r requirements.txt
   conda install pytorch torchvision torchaudio cudatoolkit=11.3 -c pytorch
   ```
