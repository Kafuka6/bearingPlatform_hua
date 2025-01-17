#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Created on 2021/2/1 20:43

@Author: Sun Jiahua

@File  : main.py

@Desc  : None
"""

import sys
import os
from scipy.io import loadmat
from tensorflow import test
import joblib  # 这个库在安装sklearn时好像会一起安装
import threading

import matplotlib.pyplot as plt
from PySide2.QtWidgets import QApplication, QMainWindow, QMessageBox, QFileDialog
from PySide2.QtGui import QPixmap, QImage
from PySide2.QtCore import Qt
from UI.main_window import Ui_MainWindow

from data_preprocess import training_stage_prepro, diagnosis_stage_prepro
from training_model import training_with_1D_CNN, training_with_LSTM, training_with_GRU, training_with_random_forest
from preprocess_train_result import plot_history_curcvs, plot_confusion_matrix, brief_classification_report, plot_metrics
from message_signal import MyMessageSignal
from diagnosis import diagnosis
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

# 定义一些全局变量
global training_end_signal  # 定义一个信号，用于当模型训练完成之后通知主线程进行弹窗提示
training_end_signal = MyMessageSignal()

global diagnosis_end_signal  # 诊断结束信号
diagnosis_end_signal = MyMessageSignal()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.init_UI()
        # 定义并初始化一些成员变量
        self.data_file_path = ''  # 初始化一个 数据所在的 文件路径
        self.model_file_path = ''  # 初始化一个 模型所在的 文件路径
        self.cache_path = os.getcwd() + '/cache'  # 所有图片等的缓存路径
        self.training_flag = False  # 是否有模型在训练的标志位
        self.model_name = ''  # 初始化一个模型名字
        self.model = ''  # 训练得到的模型
        self.classification_report = ''  # 初始化一个 分类报告
        self.score = ''  # 初始化一个模型得分


    def init_UI(self):
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        self.ui.pb_select_file.clicked.connect(self.select_file)  # 模型训练页面的 选择文件 按钮
        self.ui.pb_visual_data.clicked.connect(self.visual_data)
        self.ui.pb_start_training.clicked.connect(self.start_training)
        self.ui.pb_show_result.clicked.connect(self.show_result)
        self.ui.pb_save_model.clicked.connect(self.save_model)
        self.ui.pb_select_model.clicked.connect(self.select_model)
        self.ui.pb_real_time_diagnosis.clicked.connect(self.real_time_diagnosis)
        self.ui.pb_local_diagnosis.clicked.connect(self.local_diagnosis)

    def select_file(self):
        self.ui.pb_select_file.setEnabled(False)
        file_path, _ = QFileDialog.getOpenFileName(self,
                                                   '打开文件',  # 标题
                                                   '.',  # 默认开始打开的文件路径， . 表示在当前文件夹下
                                                   '(*.mat)'  # 文件过滤，表示只显示后缀名为 .mat 的文件
                                                   )
        if '' != file_path:  # 选择了文件, 则将路径更新，否则，保留原路径
            self.data_file_path = file_path
            self.ui.tb_train_result.setText('选择文件：' + self.data_file_path + '\n--------------')
        self.ui.pb_select_file.setEnabled(True)

    def visual_data(self):
        self.ui.pb_visual_data.setEnabled(False)

        if '' == self.data_file_path:  # 没有选择过文件
            reply = QMessageBox.information(self, '提示', '请先选择文件！', QMessageBox.Yes, QMessageBox.Yes)
            if reply == QMessageBox.Yes:
                self.ui.pb_visual_data.setEnabled(True)
                return  # 直接退出

        visual_data_pic_path = visual_data(self.data_file_path, self.cache_path)
        # 读取图片文件，进行显示
        img = QImage(visual_data_pic_path)
        img_result = img.scaled(self.ui.l_visual_data.width(), self.ui.l_visual_data.height(),  # 裁剪图片将图片大小
                                Qt.IgnoreAspectRatio,  # 保持长宽比例
                                Qt.SmoothTransformation  # 平滑处理，使图片不失真
                                )
        self.ui.l_visual_data.setPixmap(QPixmap.fromImage(img_result))
        self.ui.pb_visual_data.setEnabled(True)

    def start_training(self):
        if self.training_flag:  # 有模型在训练
            reply = QMessageBox.information(self, '提示', '正在训练模型，请等待...', QMessageBox.Yes, QMessageBox.Yes)
            if reply == QMessageBox.Yes:
                return  # 退出函数

        if '' == self.data_file_path:  # 没有选择过文件
            reply = QMessageBox.information(self, '提示', '请先选择文件！', QMessageBox.Yes, QMessageBox.Yes)
            if reply == QMessageBox.Yes:
                return  # 退出函数

        # 到这里，就是 没有模型在训练，且选择了文件
        # 提示用户确认
        select_model = self.ui.comb_select_model.currentText()  # 用户选择的 模型
        reply = QMessageBox.information(self, '提示', '确定使用“' + select_model + '”进行训练。\n请确保所有数据在一个文件夹下！',
                                        QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if reply == QMessageBox.No:
            return  # 退出函数

        # 到这里，可以开始训练了
        self.training_flag = True  # 改变标志位
        self.ui.statusbar.showMessage('正在训练模型...', 120)

        # 不同的模型，参数设置不一样
        if '随机森林' == select_model:
            signal_length = 500
            signal_number = 1000  # 每个类别中要抽取的样本的数量
            normal = False  # 是否标准化
            rate = [0.6, 0.2, 0.2]  # 训练集、测试集、验证集划分比例
        else:
            signal_length = 2048
            signal_number = 1000  # 每个类别中要抽取的样本的数量
            normal = True  # 是否标准化
            rate = [0.7, 0.2, 0.1]  # 训练集、测试集、验证集划分比例
        # 获得数据所在的文件夹  E:/fff/hhh/iii/tt.mat --> tt.mat --> E:/fff/hhh/iii/
        data_path = self.data_file_path.split('/')[-1]  # 先获得文件名
        data_path = self.data_file_path.split(data_path)[0]  # 再去掉文件路径中的文件名

        if '1D_CNN' == select_model:
            self.model_name = '1D_CNN'
            text = self.ui.tb_train_result.toPlainText()  # 获得原本显示的文字
            if test.is_gpu_available():
                self.ui.tb_train_result.setText(text + '\n模型选择：1D_CNN\n检测到GPU可用\n--------------')
            else:
                self.ui.tb_train_result.setText(text + '\n模型选择：1D_CNN\n未检测到可用GPU\n--------------')
            text = self.ui.tb_train_result.toPlainText()  # 获得原本显示的文字
            self.ui.tb_train_result.setText(text + '\n正在训练模型...\n--------------')

            # 创建子线程，训练模型
            training_thread = threading.Thread(target=CNN_1D_training,
                                               args=(data_path, signal_length, signal_number, normal, rate,
                                                     self.cache_path, self.model_name)
                                               )
            # training_thread.setDaemon(True)  # 守护线程
            training_thread.start()
            training_end_signal.send_msg.connect(self.training_end_slot)  # 信号与槽连接

        elif 'LSTM' == select_model:
            self.model_name = 'LSTM'
            text = self.ui.tb_train_result.toPlainText()  # 获得原本显示的文字
            if test.is_gpu_available():
                self.ui.tb_train_result.setText(text + '\n模型选择：LSTM\n检测到GPU可用\n--------------')
            else:
                self.ui.tb_train_result.setText(text + '\n模型选择：LSTM\n未检测到可用GPU\n--------------')
            text = self.ui.tb_train_result.toPlainText()  # 获得原本显示的文字
            self.ui.tb_train_result.setText(text + '\n正在训练模型...\n--------------')

            # 创建子线程，训练模型
            training_thread = threading.Thread(target=LSTM_training,
                                               args=(data_path, signal_length, signal_number, normal, rate,
                                                     self.cache_path, self.model_name)
                                               )
            # training_thread.setDaemon(True)  # 守护线程
            training_thread.start()
            training_end_signal.send_msg.connect(self.training_end_slot)  # 信号与槽连接

        elif 'GRU' == select_model:
            self.model_name = 'GRU'
            text = self.ui.tb_train_result.toPlainText()  # 获得原本显示的文字
            if test.is_gpu_available():
                self.ui.tb_train_result.setText(text + '\n模型选择：GRU\n检测到GPU可用\n--------------')
            else:
                self.ui.tb_train_result.setText(text + '\n模型选择：GRU\n未检测到可用GPU\n--------------')
            text = self.ui.tb_train_result.toPlainText()  # 获得原本显示的文字
            self.ui.tb_train_result.setText(text + '\n正在训练模型...\n--------------')

            # 创建子线程，训练模型
            training_thread = threading.Thread(target=GRU_training,
                                               args=(data_path, signal_length, signal_number, normal, rate,
                                                     self.cache_path, self.model_name)
                                               )
            # training_thread.setDaemon(True)  # 守护线程
            training_thread.start()
            training_end_signal.send_msg.connect(self.training_end_slot)  # 信号与槽连接

        elif '随机森林' == select_model:
            self.model_name = 'random_forest'
            text = self.ui.tb_train_result.toPlainText()  # 获得原本显示的文字
            self.ui.tb_train_result.setText(text + '\n模型选择：随机森林\n正在训练模型...\n--------------')

            # 创建子线程，训练模型
            training_thread = threading.Thread(target=random_forest_training,
                                               args=(data_path, signal_length, signal_number, normal, rate,
                                                     self.cache_path, self.model_name)
                                               )
            # training_thread.setDaemon(True)  # 守护线程
            training_thread.start()
            training_end_signal.send_msg.connect(self.training_end_slot)  # 信号与槽连接

    def training_end_slot(self, msg):
        self.model = msg['model']
        self.classification_report = msg['classification_report']
        self.score = msg['score']

        QMessageBox.information(self, '提示', '训练完成！', QMessageBox.Yes, QMessageBox.Yes)
        self.ui.statusbar.close()
        text = self.ui.tb_train_result.toPlainText()  # 获得原本显示的文字
        self.ui.tb_train_result.setText(text + '\n训练完成，模型得分：' + self.score + '\n--------------')
        self.ui.l_train_result.setText(self.classification_report)
        self.training_flag = False

    def diagnosis_end_slot(self, msg):
        pred_result = msg['pred_result']
        text = self.ui.tb_diagnosis_result.toPlainText()
        self.ui.tb_diagnosis_result.setText(text + '\n诊断结果：' + pred_result + '\n--------------')
        self.ui.pb_real_time_diagnosis.setEnabled(True)
        self.ui.pb_local_diagnosis.setEnabled(True)

    def show_result(self):
        if '' == self.model_name:  # 说明还没有训练过模型
            reply = QMessageBox.information(self, '提示', '你还没有训练模型哦！', QMessageBox.Yes, QMessageBox.Yes)
            if reply == QMessageBox.Yes:
                return

        show_mode = self.ui.buttonGroup.checkedId()
        # print(show_mode)
        # TODO: 这里的 Id 自己测出来的, 应该还有别的方法直接得到所选框的内容
        if -2 == show_mode:  # 展示 分类报告
            self.ui.l_train_result.setText(self.classification_report)
        elif -3 == show_mode:  # 展示 混淆矩阵
            # 读取图片文件，进行显示
            img = QImage(self.cache_path + '/' + self.model_name + '_confusion_matrix.png')
            img_result = img.scaled(self.ui.l_train_result.width(), self.ui.l_train_result.height(),  # 裁剪图片将图片大小
                                    Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            self.ui.l_train_result.setPixmap(QPixmap.fromImage(img_result))
        elif -4 == show_mode:  # 展示 ROC曲线
            # 读取图片文件，进行显示
            img = QImage(self.cache_path + '/' + self.model_name + '_ROC_Curves.png')
            img_result = img.scaled(self.ui.l_train_result.width(), self.ui.l_train_result.height(),  # 裁剪图片将图片大小
                                    Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            self.ui.l_train_result.setPixmap(QPixmap.fromImage(img_result))
        elif -5 == show_mode:  # 展示 精度召回曲线
            # 读取图片文件，进行显示
            img = QImage(self.cache_path + '/' + self.model_name + '_Precision_Recall_Curves.png')
            img_result = img.scaled(self.ui.l_train_result.width(), self.ui.l_train_result.height(),  # 裁剪图片将图片大小
                                    Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            self.ui.l_train_result.setPixmap(QPixmap.fromImage(img_result))
        elif -6 == show_mode:  # 展示 损失曲线
            if 'random_forest' == self.model_name:  # 随机森林没有损失曲线
                QMessageBox.information(self, '提示', '随机森林模型没有损失曲线哦！', QMessageBox.Yes, QMessageBox.Yes)
            else:
                # 读取图片文件，进行显示
                img = QImage(self.cache_path + '/' + self.model_name + '_train_valid_loss.png')
                img_result = img.scaled(self.ui.l_train_result.width(), self.ui.l_train_result.height(),  # 裁剪图片将图片大小
                                        Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                self.ui.l_train_result.setPixmap(QPixmap.fromImage(img_result))
        elif -7 == show_mode:  # 展示 正确率曲线
            if 'random_forest' == self.model_name:  # 随机森林没有正确率曲线
                QMessageBox.information(self, '提示', '随机森林模型没有正确率曲线哦！', QMessageBox.Yes, QMessageBox.Yes)
            else:
                # 读取图片文件，进行显示
                img = QImage(self.cache_path + '/' + self.model_name + '_train_valid_acc.png')
                img_result = img.scaled(self.ui.l_train_result.width(), self.ui.l_train_result.height(),  # 裁剪图片将图片大小
                                        Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
                self.ui.l_train_result.setPixmap(QPixmap.fromImage(img_result))

    def save_model(self):
        if '' == self.model_name:  # 说明还没有训练过模型
            reply = QMessageBox.information(self, '提示', '你还没有训练模型哦！', QMessageBox.Yes, QMessageBox.Yes)
            if reply == QMessageBox.Yes:
                return

        if 'random_forest' == self.model_name:
            save_path, _ = QFileDialog.getSaveFileName(self,
                                                       '保存文件',  # 标题
                                                       './' + self.model_name + '.m',  # 默认开始打开的文件路径， . 表示在当前文件夹下, 后面接的默认文件名
                                                       '(*.m)'  # 文件过滤，表示只显示后缀名为 .mat 的文件
                                                       )
            if '' == save_path:  # 没有确定保存。这里也可以通过 变量 _ 来判断
                return
            # print(save_path)
            joblib.dump(self.model, save_path)  # 存储
        else:
            save_path, _ = QFileDialog.getSaveFileName(self, '保存文件', './' + self.model_name + '.h5', '(*.h5)')
            if '' == save_path:  # 没有确定保存。这里也可以通过 变量 _ 来判断
                return
            self.model.save(save_path)
        text = self.ui.tb_train_result.toPlainText()  # 获得原本显示的文字
        self.ui.tb_train_result.setText(text + "\n模型保存成功\n--------------")

    def select_model(self):
        self.ui.pb_select_model.setEnabled(False)
        file_path, _ = QFileDialog.getOpenFileName(self, '选择模型', '.', '(*.m *.h5)')
        if '' != file_path:  # 选择了文件, 则将路径更新，否则，保留原路径
            self.model_file_path = file_path
            self.ui.tb_diagnosis_result.setText('选择文件：' + self.model_file_path + '\n--------------')
        self.ui.pb_select_model.setEnabled(True)

    def real_time_diagnosis(self):
        self.ui.pb_real_time_diagnosis.setEnabled(False)
        self.ui.pb_local_diagnosis.setEnabled(False)  # 同一时间只能进行一种诊断

        if '' == self.model_file_path:  # 没有选择过模型
            reply = QMessageBox.information(self, '提示', '你还没有选择模型哦！', QMessageBox.Yes, QMessageBox.Yes)
            if QMessageBox.Yes == reply:
                self.ui.pb_real_time_diagnosis.setEnabled(True)
                self.ui.pb_local_diagnosis.setEnabled(True)
                return

        text = self.ui.tb_diagnosis_result.toPlainText()
        self.ui.tb_diagnosis_result.setText(text + '\n实时诊断：正在采集数据...\n--------------')

        # TODO: 这里通过读取指定的文件夹数据来模拟实时采集数据
        real_time_data_path = os.getcwd() + '/real_time_data/0HP/48k_Drive_End_B007_0_122.mat'

        # 读取完数据后，自动可视化数据
        visual_data_pic_path = visual_data(real_time_data_path, self.cache_path)
        # 读取图片文件，进行显示
        img = QImage(visual_data_pic_path)
        img_result = img.scaled(self.ui.l_visual_diagnosis_data.width(), self.ui.l_visual_diagnosis_data.height(),  # 裁剪图片将图片大小
                                Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        self.ui.l_visual_diagnosis_data.setPixmap(QPixmap.fromImage(img_result))
        text = self.ui.tb_diagnosis_result.toPlainText()
        self.ui.tb_diagnosis_result.setText(text + '\n实时诊断：正在诊断..\n--------------')

        # 开个子线程进行故障诊断
        diagnosis_end_signal.send_msg.connect(self.diagnosis_end_slot)  # 信号与槽连接
        diagnosis_thread = threading.Thread(target=fault_diagnosis, args=(self.model_file_path, real_time_data_path))
        diagnosis_thread.start()

    def local_diagnosis(self):
        self.ui.pb_local_diagnosis.setEnabled(False)
        self.ui.pb_real_time_diagnosis.setEnabled(False)  # 同一时间只能进行一种诊断

        file_path, _ = QFileDialog.getOpenFileName(self, '选择数据', '.', '(*.mat)')
        if '' == file_path:  # 没有选择文件，也就是退出了本地诊断
            self.ui.pb_real_time_diagnosis.setEnabled(True)
            self.ui.pb_local_diagnosis.setEnabled(True)
            return

        text = self.ui.tb_diagnosis_result.toPlainText()
        self.ui.tb_diagnosis_result.setText(text + '\n选择文件：' + file_path + '\n--------------')

        if '' == self.model_file_path:  # 没有选择过模型
            reply = QMessageBox.information(self, '提示', '你还没有选择模型哦！', QMessageBox.Yes, QMessageBox.Yes)
            if QMessageBox.Yes == reply:
                self.ui.pb_real_time_diagnosis.setEnabled(True)
                self.ui.pb_local_diagnosis.setEnabled(True)
                return

        text = self.ui.tb_diagnosis_result.toPlainText()
        self.ui.tb_diagnosis_result.setText(text + '\n本地诊断：正在读取数据...\n--------------')

        # 读取完数据后，自动可视化数据
        visual_data_pic_path = visual_data(file_path, self.cache_path)
        # 读取图片文件，进行显示
        img = QImage(visual_data_pic_path)
        img_result = img.scaled(self.ui.l_visual_diagnosis_data.width(), self.ui.l_visual_diagnosis_data.height(),  # 裁剪图片将图片大小
                                Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        self.ui.l_visual_diagnosis_data.setPixmap(QPixmap.fromImage(img_result))

        text = self.ui.tb_diagnosis_result.toPlainText()
        self.ui.tb_diagnosis_result.setText(text + '\n实时诊断：正在诊断..\n--------------')

        # 开个子线程进行故障诊断
        diagnosis_end_signal.send_msg.connect(self.diagnosis_end_slot)  # 信号与槽连接
        diagnosis_thread = threading.Thread(target=fault_diagnosis,
                                            args=(self.model_file_path, file_path))
        diagnosis_thread.start()

    def closeEvent(self, event):
        '''
        重写关闭窗口函数：在点击关闭窗口后，将缓存文件夹下的文件全部删除
        :param event:
        :return:
        '''
        file_names = os.listdir(self.cache_path)
        for file_name in file_names:
            os.remove(self.cache_path + '/' + file_name)

        sys.exit()


def visual_data(data_path, cache_path):
    '''
    可视化数据
    :param data_path: 数据路径
    :param cache_path: 可视化的图缓存的路径
    :return:
    '''
    file = loadmat(data_path)  # 加载文件，这里得到的文件是一个 字典
    file_keys = file.keys()
    for key in file_keys:
        if 'DE' in key:  # DE: 驱动端测得的振动数据
            global data  # 定义一个全局变量
            data = file[key][:2500]  # 截取数据的前2500个数据点进行绘图

    # 解决无法显示中文问题
    plt.rcParams['font.sans-serif'] = ['SimHei']
    plt.rcParams['axes.unicode_minus'] = False
    plt.figure(figsize=(15, 7))
    plt.plot(data)
    # plt.title('驱动端测得的振动数据')

    # TODO: 这里预想的是，直接在内存中画图，直接显示到页面上，但暂时不会。所以采用 先将图片保存到本地，再读取文件显示
    # 获取图片的保存路径 --- 先获得文件名，在与路径拼接
    visual_data_pic_name = data_path.split('/')[-1].split('.')[0]  # 先按 / 切割，获得最后的文件名，然后按 . 切割，去掉后缀名
    visual_data_pic_path = cache_path + '/' + visual_data_pic_name + '.png'
    # 保存图片
    plt.savefig(visual_data_pic_path,
                dpi=150, bbox_inches='tight'  # 去除输出图片四周的空白，使图片更加紧凑
                )
    # plt.show()  # 要先保存图片，再show。先show的话，plt在show完就没了，保存的就是一张空白
    plt.close()  # 保存完图片后，要将plt关掉，不然，后面画图可能都会画在一张画布上

    return visual_data_pic_path


def CNN_1D_training(data_path, signal_length, signal_number, normal, rate, save_path, model_name):
    '''
    训练 1D_CNN 模型
    :param data_path: 数据路径
    :param signal_length: 信号长度
    :param signal_number: 型号个数
    :param normal: 是否标准化
    :param rate: 训练集，验证集，测试集 划分比例
    :param save_path: 训练完后各种图的保存路径
    :param model_name: 模型名字
    :return:
    '''
    X_train, y_train, X_valid, y_valid, X_test, y_test = training_stage_prepro(data_path, signal_length, signal_number,
                                                                               normal, rate, enhance=False)
    model, history, score = training_with_1D_CNN(X_train, y_train, X_valid, y_valid, X_test, y_test, batch_size=128,
                                                 epochs=20, num_classes=10)
    plot_history_curcvs(history, save_path, model_name)  # 绘制 训练集合验证集 损失曲线和正确率曲线
    plot_confusion_matrix(model, model_name, save_path, X_test, y_test)  # 绘制混淆矩阵
    classification_report = brief_classification_report(model, model_name, X_test, y_test)  # 计算分类报告
    plot_metrics(model, model_name, save_path, X_test, y_test)  # 绘制 召回率曲线和精确度曲线
    # sleep(3)

    # 发送信号通知主线程训练完成，让主线程发个弹窗，通知用户, 同时将模型得分发送过去以便显示
    # training_end_signal.run()
    msg = {'model': model, 'classification_report': classification_report, 'score': str(score)}
    training_end_signal.send_msg.emit(msg)


def LSTM_training(data_path, signal_length, signal_number, normal, rate, save_path, model_name):
    '''
    训练 LSTM 模型
    :param data_path: 数据路径
    :param signal_length: 信号长度
    :param signal_number: 型号个数
    :param normal: 是否标准化
    :param rate: 训练集，验证集，测试集 划分比例
    :param save_path: 训练完后各种图的保存路径
    :param model_name: 模型名字
    :return:
    '''
    X_train, y_train, X_valid, y_valid, X_test, y_test = training_stage_prepro(data_path, signal_length, signal_number,
                                                                               normal, rate, enhance=False)
    model, history, score = training_with_LSTM(X_train, y_train, X_valid, y_valid, X_test, y_test, batch_size=128,
                                               epochs=60, num_classes=10)
    plot_history_curcvs(history, save_path, model_name)  # 绘制 训练集合验证集 损失曲线和正确率曲线
    plot_confusion_matrix(model, model_name, save_path, X_test, y_test)  # 绘制混淆矩阵
    classification_report = brief_classification_report(model, model_name, X_test, y_test)  # 计算分类报告
    plot_metrics(model, model_name, save_path, X_test, y_test)  # 绘制 召回率曲线和精确度曲线
    # sleep(3)

    # 发送信号通知主线程训练完成，让主线程发个弹窗，通知用户
    # training_end_signal.run()
    msg = {'model': model, 'classification_report': classification_report, 'score': str(score)}
    training_end_signal.send_msg.emit(msg)


def GRU_training(data_path, signal_length, signal_number, normal, rate, save_path, model_name):
    '''
    训练 GRU 模型
    :param data_path: 数据路径
    :param signal_length: 信号长度
    :param signal_number: 型号个数
    :param normal: 是否标准化
    :param rate: 训练集，验证集，测试集 划分比例
    :param save_path: 训练完后各种图的保存路径
    :param model_name: 模型名字
    :return:
    '''
    X_train, y_train, X_valid, y_valid, X_test, y_test = training_stage_prepro(data_path, signal_length, signal_number,
                                                                               normal, rate, enhance=False)
    model, history, score = training_with_GRU(X_train, y_train, X_valid, y_valid, X_test, y_test, batch_size=128,
                                              epochs=60, num_classes=10)
    plot_history_curcvs(history, save_path, model_name)  # 绘制 训练集合验证集 损失曲线和正确率曲线
    plot_confusion_matrix(model, model_name, save_path, X_test, y_test)  # 绘制混淆矩阵
    classification_report = brief_classification_report(model, model_name, X_test, y_test)  # 计算分类报告
    plot_metrics(model, model_name, save_path, X_test, y_test)  # 绘制 召回率曲线和精确度曲线
    # sleep(3)

    # 发送信号通知主线程训练完成，让主线程发个弹窗，通知用户
    # training_end_signal.run()
    msg = {'model': model, 'classification_report': classification_report, 'score': str(score)}
    training_end_signal.send_msg.emit(msg)


def random_forest_training(data_path, signal_length, signal_number, normal, rate, save_path, model_name):
    '''
    训练 随机森林 模型
    :param data_path: 数据路径
    :param signal_length: 信号长度
    :param signal_number: 型号个数
    :param normal: 是否标准化
    :param rate: 训练集，验证集，测试集 划分比例
    :param save_path: 训练完后各种图的保存路径
    :param model_name: 模型名字
    :return:
    '''
    X_train, y_train, X_valid, y_valid, X_test, y_test = training_stage_prepro(data_path, signal_length, signal_number,
                                                                               normal, rate, enhance=False)
    model, score, X_train_feature_extraction, X_test_feature_extraction = training_with_random_forest(X_train, y_train,
                                                                                                      X_valid, y_valid,
                                                                                                      X_test, y_test)
    # plot_history_curcvs(history, save_path, model_name)  # 绘制 训练集合验证集 损失曲线和正确率曲线 --- 随机森林没有
    plot_confusion_matrix(model, model_name, save_path, X_test_feature_extraction, y_test)  # 绘制混淆矩阵
    classification_report = brief_classification_report(model, model_name, X_test_feature_extraction, y_test)  # 计算分类报告
    plot_metrics(model, model_name, save_path, X_test_feature_extraction, y_test)  # 绘制 召回率曲线和精确度曲线
    # sleep(3)

    # 发送信号通知主线程训练完成，让主线程发个弹窗，通知用户
    # training_end_signal.run()
    msg = {'model': model, 'classification_report': classification_report, 'score': str(score)}
    training_end_signal.send_msg.emit(msg)


def fault_diagnosis(model_file_path, real_time_data_path):
    '''
    使用模型进行故障诊断
    :param model_file_path: 模型路径
    :param real_time_data_path: 数据路径
    :return:
    '''
    suffix = model_file_path.split('/')[-1].split('.')[-1]  # 获得所选模型的后缀名
    if 'm' == suffix:  # 说明是随机森林
        diagnosis_samples = diagnosis_stage_prepro(real_time_data_path, 500, 500, False)
        pred_result = diagnosis(diagnosis_samples, model_file_path)
    else:
        diagnosis_samples = diagnosis_stage_prepro(real_time_data_path, 2048, 500, True)
        pred_result = diagnosis(diagnosis_samples, model_file_path)

    # 诊断完成，将结果发送回去
    msg = {'pred_result': pred_result}
    diagnosis_end_signal.send_msg.emit(msg)


if __name__ == '__main__':
    app = QApplication(sys.argv)
    main = MainWindow()
    main.show()
    sys.exit(app.exec_())
