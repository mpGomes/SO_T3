#!/bin/sh
MOUNTPOINT=mountpoint
DISK=disk.img
echo "will run in foreground for debug purposes. run the  umount/fusermount -u   from another terminal"
echo "mounting $DISK in $MOUNTPOINT..."
#./sofs.py -f -d $MOUNTPOINT -o device=$DISK
./sofs.py -f $MOUNTPOINT -o device=$DISK
echo "Done!"
